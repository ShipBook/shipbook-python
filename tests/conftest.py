import base64
import json
import time
from types import SimpleNamespace

import pytest

from shipbook import _state
from shipbook.cloud_uploader import CloudUploader
from shipbook.config import Config
from shipbook.connection_client import Response
from shipbook.session_manager import SessionManager
from shipbook.storage import Storage


def make_jwt(exp: float) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": int(exp)}).encode())
        .decode()
        .rstrip("=")
    )
    return f"{header}.{payload}.sig"


def login_response(exp_offset: float = 3600, config=None) -> Response:
    token = make_jwt(time.time() + exp_offset)
    return Response(ok=True, status=200, reason="OK", data={"token": token, "config": config})


class FakeConnection:
    """Stand-in for ConnectionClient that records requests and returns canned
    responses, keyed by path."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.base_url = "https://api.test/v2/"
        self._responses = {}

    def set_deps(self, get_token, refresh_token) -> None:
        self.get_token = get_token
        self.refresh_token = refresh_token

    def set_base_url(self, url: str) -> None:
        self.base_url = url

    def when(self, path: str, response: Response) -> None:
        self._responses[path] = response

    def request(
        self, path: str, body=None, method: str = "GET", _retried: bool = False
    ) -> Response:
        self.requests.append({"path": path, "body": body, "method": method})
        return self._responses.get(path, Response(ok=True, status=200, reason="OK", data={}))

    def ingested_sessions(self) -> list[dict]:
        out: list[dict] = []
        for r in self.requests:
            if r["path"] == "sessions/ingest":
                out.extend(r["body"]["sessions"])
        return out


@pytest.fixture
def storage(tmp_path):
    return Storage(directory=str(tmp_path))


@pytest.fixture
def connection():
    return FakeConnection()


@pytest.fixture
def config():
    return Config.default()


@pytest.fixture
def uploader(connection, storage, config):
    # A logged-in session manager so get_token() returns a live token.
    sm = SessionManager(connection)  # type: ignore[arg-type]
    connection.when("auth/loginSdkServer", login_response())
    sm.login("app", "key")
    up = CloudUploader(
        connection, sm, storage, config, app_version="1.0.0", start_worker=False
    )
    yield up
    sm.destroy()


@pytest.fixture
def active_runtime(uploader, config):
    """Wire the module-global state so ShipbookHandler.emit routes to our
    uploader, then tear it down."""
    runtime = SimpleNamespace(config=config, uploader=uploader)
    _state.set_active(runtime)
    yield runtime
    _state.set_active(None)
