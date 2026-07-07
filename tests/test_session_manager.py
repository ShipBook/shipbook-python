import time

from shipbook.connection_client import Response
from shipbook.session_manager import SessionManager
from tests.conftest import login_response, make_jwt


def test_login_stores_token_and_returns_config(connection):
    connection.when(
        "auth/loginSdkServer",
        Response(
            ok=True,
            status=200,
            reason="OK",
            data={"token": make_jwt(time.time() + 3600), "config": {"loggers": []}},
        ),
    )
    sm = SessionManager(connection)  # type: ignore[arg-type]
    config = sm.login("app", "key")
    assert config == {"loggers": []}
    assert sm.get_token() is not None
    sm.destroy()


def test_get_token_none_when_expired(connection):
    connection.when("auth/loginSdkServer", login_response(exp_offset=-10))
    sm = SessionManager(connection)  # type: ignore[arg-type]
    sm.login("app", "key")
    assert sm.get_token() is None
    sm.destroy()


def test_4xx_login_does_not_retry(connection):
    connection.when(
        "auth/loginSdkServer",
        Response(ok=False, status=403, reason="Forbidden", data={"name": "AuthError"}),
    )
    sm = SessionManager(connection)  # type: ignore[arg-type]
    assert sm.login("bad", "creds") is None
    assert sm.get_token() is None
    sm.destroy()


def test_jwt_exp_decode():
    exp = int(time.time()) + 12345
    assert SessionManager._jwt_exp(make_jwt(exp)) == exp
    assert SessionManager._jwt_exp("not-a-jwt") is None


def test_refresh_reads_token_lifetime_for_scheduling(connection, monkeypatch):
    scheduled = {}

    def fake_schedule(self, delay, fn):
        scheduled["delay"] = delay

    monkeypatch.setattr(SessionManager, "_schedule", fake_schedule)
    connection.when("auth/loginSdkServer", login_response(exp_offset=1000))
    sm = SessionManager(connection)  # type: ignore[arg-type]
    sm.login("app", "key")
    # Refresh scheduled at ~80% of the ~1000s lifetime.
    assert 750 < scheduled["delay"] < 850
