import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from shipbook.connection_client import ConnectionClient
from shipbook.session_manager import SessionManager
from tests.conftest import make_jwt

LOGIN = "/v2/auth/loginSdkServer"
INGEST = "/v2/sessions/ingest"


class FakeApi:
    """A local HTTP server: the real ConnectionClient talks to it, so its 401 handling is run."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        # Per path, the answers in order; the last one repeats.
        self.answers: dict[str, list[tuple[int, dict, dict]]] = {}
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                api.paths.append(self.path)
                answers = api.answers[self.path]
                status, body, headers = answers.pop(0) if len(answers) > 1 else answers[0]
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/v2/"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def answer(self, path: str, status: int, body: dict, headers=None) -> None:
        self.answers.setdefault(path, []).append((status, body, headers or {}))

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def api():
    fake = FakeApi()
    yield fake
    fake.close()


@pytest.fixture
def session_manager(api):
    connection = ConnectionClient()
    connection.set_base_url(api.url)
    sm = SessionManager(connection)
    connection.set_deps(get_token=sm.get_token, refresh_token=sm.refresh)
    yield sm
    sm.destroy()


def _logged_in():
    return 200, {"token": make_jwt(time.time() + 3600), "config": {"loggers": []}}


def test_a_wrong_app_key_is_asked_once(api, session_manager):
    api.answer(LOGIN, 401, {"name": "AuthError", "message": "Unauthorized"})

    assert session_manager.login("app", "wrong-key") is None

    assert api.paths == [LOGIN]
    assert session_manager.get_token() is None


def test_an_expired_token_is_refreshed_and_the_request_sent_again(api, session_manager):
    api.answer(LOGIN, *_logged_in())
    api.answer(INGEST, 401, {"name": "TokenExpired", "message": "Token Expired"})
    api.answer(INGEST, 200, {"success": True})
    session_manager.login("app", "key")

    resp = session_manager._connection.request("sessions/ingest", {"sessions": []}, "POST")

    assert resp.ok
    assert api.paths == [LOGIN, INGEST, LOGIN, INGEST]


def test_a_token_that_stays_expired_is_refreshed_only_once(api, session_manager):
    api.answer(LOGIN, *_logged_in())
    api.answer(INGEST, 401, {"name": "TokenExpired", "message": "Token Expired"})
    session_manager.login("app", "key")

    resp = session_manager._connection.request("sessions/ingest", {"sessions": []}, "POST")

    assert resp.status == 401
    assert api.paths == [LOGIN, INGEST, LOGIN, INGEST]


def test_a_401_for_another_reason_does_not_log_in_again(api, session_manager):
    api.answer(LOGIN, *_logged_in())
    api.answer(INGEST, 401, {"name": "AuthError", "message": "Unauthorized"})
    session_manager.login("app", "key")

    resp = session_manager._connection.request("sessions/ingest", {"sessions": []}, "POST")

    assert resp.status == 401
    assert api.paths == [LOGIN, INGEST]


def test_an_app_deleted_while_running_stops_the_sdk(api, session_manager):
    api.answer(LOGIN, *_logged_in())
    api.answer(LOGIN, 401, {"name": "AuthError", "message": "Unauthorized"})
    api.answer(INGEST, 401, {"name": "TokenExpired", "message": "Token Expired"})
    session_manager.login("app", "key")

    resp = session_manager._connection.request("sessions/ingest", {"sessions": []}, "POST")

    assert resp.status == 401
    assert api.paths == [LOGIN, INGEST, LOGIN]
    # Without a token the uploader sends nothing more.
    assert session_manager.get_token() is None


def test_the_wait_the_server_asks_for_is_read(api, session_manager):
    api.answer(INGEST, 429, {"name": "TooManyRequestsError"}, {"Retry-After": "120"})

    resp = session_manager._connection.request("sessions/ingest", {"sessions": []}, "POST")

    assert resp.status == 429
    assert resp.retry_after == 120
