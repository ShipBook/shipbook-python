import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

DEFAULT_BASE_URL = "https://api.shipbook.io/v2/"
_TIMEOUT = 30
# The error name the server answers a 401 with when the token is merely too old.
TOKEN_EXPIRED = "TokenExpired"


@dataclass
class Response:
    ok: bool
    status: int
    reason: str
    data: Optional[Any] = None
    text: str = ""
    # Seconds the server asked to wait (the Retry-After header), when it sent a number.
    retry_after: Optional[int] = None


class ConnectionClient:
    def __init__(self) -> None:
        self.base_url = DEFAULT_BASE_URL
        self._get_token: Callable[[], Optional[str]] = lambda: None
        self._refresh_token: Callable[[], bool] = lambda: False

    def set_deps(
        self,
        get_token: Callable[[], Optional[str]],
        refresh_token: Callable[[], bool],
    ) -> None:
        self._get_token = get_token
        self._refresh_token = refresh_token

    def set_base_url(self, url: str) -> None:
        self.base_url = url if url.endswith("/") else url + "/"

    def request(
        self,
        path: str,
        body: Optional[Any] = None,
        method: str = "GET",
        allow_refresh: bool = True,
    ) -> Response:
        url = self.base_url + path
        headers = {"Content-Type": "application/json"}
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
                return Response(
                    ok=True,
                    status=resp.status,
                    reason=resp.reason,
                    data=self._parse(raw),
                    text=raw,
                )
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            data = self._parse(raw)
            # As in the other SDKs, only an expired token is refreshed, and once per request.
            expired = e.code == 401 and isinstance(data, dict) and data.get("name") == TOKEN_EXPIRED
            if expired and allow_refresh and self._refresh_token():
                return self.request(path, body, method, allow_refresh=False)
            retry_after = e.headers.get("Retry-After", "") if e.headers else ""
            return Response(
                ok=False,
                status=e.code,
                reason=e.reason or "",
                data=data,
                text=raw,
                retry_after=int(retry_after) if retry_after.isdigit() else None,
            )
        except urllib.error.URLError as e:
            return Response(ok=False, status=0, reason=str(e.reason), text=str(e.reason))

    @staticmethod
    def _parse(raw: str) -> Optional[Any]:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
