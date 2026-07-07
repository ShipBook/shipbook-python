import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

DEFAULT_BASE_URL = "https://api.shipbook.io/v2/"
_TIMEOUT = 30


@dataclass
class Response:
    ok: bool
    status: int
    reason: str
    data: Optional[Any] = None
    text: str = ""


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
        _retried: bool = False,
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
            if e.code == 401 and not _retried and self._refresh_token():
                return self.request(path, body, method, _retried=True)
            return Response(
                ok=False,
                status=e.code,
                reason=e.reason or "",
                data=self._parse(raw),
                text=raw,
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
