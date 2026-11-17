import base64
import binascii
import json
import threading
import time
from typing import Callable, Optional

from ._inner_log import inner_log
from .connection_client import ConnectionClient

_LOGIN_RETRY_SECONDS = 60
_MAX_LOGIN_RETRY_SECONDS = 3600
_TOO_MANY_REQUESTS = 429


class SessionManager:
    """Owns the server-SDK auth token: logs in via ``auth/loginSdkServer``,
    decodes the JWT ``exp``, and proactively re-logs in at 80% of the token
    lifetime. ``get_token`` returns ``None`` once the token is stale so the
    uploader buffers instead of sending with a dead token."""

    def __init__(self, connection: ConnectionClient) -> None:
        self._connection = connection
        self._token: Optional[str] = None
        self._expires_at = 0.0
        self._app_id: Optional[str] = None
        self._app_key: Optional[str] = None
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.RLock()
        self.on_config: Optional[Callable[[dict], None]] = None

    def login(self, app_id: str, app_key: str) -> Optional[dict]:
        self._app_id = app_id
        self._app_key = app_key
        return self._do_login()

    def get_token(self) -> Optional[str]:
        with self._lock:
            if self._token and time.time() < self._expires_at:
                return self._token
            return None

    def refresh(self) -> bool:
        """Connection-client callback for an expired token: log in again, apply the new config."""
        config = self._do_login()
        if config is None:
            return False
        if self.on_config:
            self.on_config(config)
        return True

    def after_fork(self) -> None:
        """In a forked child: the parent's refresh timer thread is gone and its lock may be held."""
        self._lock = threading.RLock()
        self._timer = None
        if self._token:
            self._schedule(max((self._expires_at - time.time()) * 0.8, 1), self._proactive_refresh)

    def destroy(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _do_login(self) -> Optional[dict]:
        assert self._app_id is not None and self._app_key is not None
        # A login can't be fixed by logging in: refreshing on its own 401 would log in without end.
        resp = self._connection.request(
            "auth/loginSdkServer",
            {"appId": self._app_id, "appKey": self._app_key},
            "POST",
            allow_refresh=False,
        )
        if not resp.ok or not resp.data:
            if 400 <= resp.status < 500 and resp.status != _TOO_MANY_REQUESTS:
                # Wrong credentials or a deleted app: no retry, and the old token is dropped.
                inner_log.error(
                    "login rejected with %s - check app_id and app_key; not retrying: %s",
                    resp.status,
                    resp.text[:200],
                )
                self._drop_token()
                return None
            delay = min(max(resp.retry_after or 0, _LOGIN_RETRY_SECONDS), _MAX_LOGIN_RETRY_SECONDS)
            inner_log.warning(
                "login failed (%s %s), trying again in %ss", resp.status, resp.reason, delay
            )
            self._schedule(delay, self._proactive_refresh)
            return None

        self._set_token(resp.data.get("token"))
        inner_log.info("logged in, the token is good for %ds", self._expires_at - time.time())
        return resp.data.get("config")

    def _drop_token(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _set_token(self, token: Optional[str]) -> None:
        with self._lock:
            self._token = token
            now = time.time()
            exp = self._jwt_exp(token) if token else None
            self._expires_at = exp if exp else now + 3600
            delay = max((self._expires_at - now) * 0.8, 1)
        self._schedule(delay, self._proactive_refresh)

    def _proactive_refresh(self) -> None:
        config = self._do_login()
        if config is not None and self.on_config:
            self.on_config(config)

    def _schedule(self, delay: float, fn: Callable[[], None]) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(delay, fn)
            self._timer.daemon = True
            self._timer.start()

    @staticmethod
    def _jwt_exp(token: str) -> Optional[float]:
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = payload.get("exp")
            return float(exp) if exp is not None else None
        except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
            return None
