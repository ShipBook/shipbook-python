from shipbook import context
from shipbook.connection_client import Response
from shipbook.models.message import Message
from shipbook.models.request_context import RequestContext
from shipbook.models.user import User
from shipbook.severity import Severity


def _msg(severity=Severity.Info, message="hi"):
    return Message(severity=severity, message=message, tag="myapp")


def test_low_severity_does_not_trigger_immediate_flush(uploader):
    uploader.push(_msg(Severity.Info))
    assert uploader._flush_now is False


def test_error_triggers_immediate_flush(uploader):
    uploader.push(_msg(Severity.Error))
    assert uploader._flush_now is True


def test_flush_size_cap_triggers_flush(uploader):
    uploader._config.flush_size = 3
    for _ in range(3):
        uploader.push(_msg(Severity.Info))
    assert uploader._flush_now is True


def test_send_groups_logs_into_session_payload(uploader, connection):
    uploader.push(_msg(Severity.Info, "one"))
    uploader.push(_msg(Severity.Info, "two"))
    uploader._send()

    sessions = connection.ingested_sessions()
    assert len(sessions) == 1
    session = sessions[0]
    assert session["platform"] == "node"
    assert session["isBackground"] is True
    assert session["sdkInfo"]["version"].startswith("python:")
    assert session["deviceInfo"]["udid"]
    messages = [log["message"] for log in session["logs"]]
    assert messages == ["one", "two"]
    assert session["logs"][0]["type"] == "message"


def test_send_binds_request_context_user_and_trace(uploader, connection):
    ctx = RequestContext(
        session_id="sess-1",
        trace_id="trace-abc",
        user=User(user_id="u1", email="u@x.com"),
        metadata={"ip": "1.2.3.4"},
        is_background=False,
    )
    with context.run(ctx):
        uploader.push(_msg(Severity.Info, "in-request"))
    uploader._send()

    session = connection.ingested_sessions()[0]
    assert session["sessionId"] == "sess-1"
    assert session["isBackground"] is False
    assert session["userInfo"]["userId"] == "u1"
    assert session["metadata"]["ip"] == "1.2.3.4"
    assert session["logs"][0]["traceId"] == "trace-abc"


def test_send_noop_without_token(connection, storage, config):
    from shipbook.cloud_uploader import CloudUploader
    from shipbook.session_manager import SessionManager

    sm = SessionManager(connection)  # never logged in → no token
    up = CloudUploader(connection, sm, storage, config, start_worker=False)
    up.push(_msg(Severity.Info))
    up.push(_msg(Severity.Info))
    up._send()
    assert connection.ingested_sessions() == []


def test_failed_ingest_requeues(uploader, connection):
    connection.when("sessions/ingest", Response(ok=False, status=500, reason="err"))
    uploader.push(_msg(Severity.Info, "keep-me"))
    uploader._send()
    # Records were put back; a subsequent successful send delivers them.
    connection.when(
        "sessions/ingest", Response(ok=True, status=200, reason="OK", data={"success": True})
    )
    uploader._send()
    sessions = connection.ingested_sessions()
    assert any(log["message"] == "keep-me" for s in sessions for log in s["logs"])
