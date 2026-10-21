import os
import threading
import time

from shipbook import context
from shipbook.cloud_uploader import CloudUploader
from shipbook.connection_client import Response
from shipbook.models.exception import ExceptionLog
from shipbook.models.message import Message
from shipbook.models.request_context import RequestContext
from shipbook.models.request_event import (
    RequestEvent,
    RequestEventPhase,
    RequestKind,
    RequestOutcome,
)
from shipbook.models.user import User
from shipbook.session_manager import SessionManager
from shipbook.severity import Severity
from tests.conftest import config_with, login_response


def _msg(severity=Severity.Info, message="hi"):
    return Message(severity=severity, message=message, tag="myapp")


def _messages(connection):
    return [log.get("message") for s in connection.ingested_sessions() for log in s["logs"]]


def _ingest_calls(connection):
    return [r for r in connection.requests if r["path"] == "sessions/ingest"]


def test_send_groups_logs_into_session_payload(uploader, connection):
    uploader.push(_msg(Severity.Info, "one"))
    uploader.push(_msg(Severity.Info, "two"))
    uploader.flush()

    sessions = connection.ingested_sessions()
    assert len(sessions) == 1
    session = sessions[0]
    assert session["platform"] == "node"
    assert session["isBackground"] is True
    assert session["sdkInfo"]["version"].startswith("python:")
    assert session["deviceInfo"]["udid"]
    assert [log["message"] for log in session["logs"]] == ["one", "two"]
    assert session["logs"][0]["type"] == "message"


def test_send_binds_request_context(uploader, connection):
    ctx = RequestContext(
        session_id="sess-1",
        trace_id="trace-abc",
        request_id="req-1",
        caller_session_link="1:client-app:client-sess",
        user=User(user_id="u1", email="u@x.com"),
        metadata={"ip": "1.2.3.4"},
        is_background=False,
    )
    with context.run(ctx):
        uploader.push(_msg(Severity.Info, "in-request"))
    uploader.flush()

    session = connection.ingested_sessions()[0]
    assert session["sessionId"] == "sess-1"
    assert session["isBackground"] is False
    assert session["userInfo"]["userId"] == "u1"
    assert session["metadata"]["ip"] == "1.2.3.4"
    assert session["callerSessionLink"] == "1:client-app:client-sess"
    log = session["logs"][0]
    assert log["traceId"] == "trace-abc"
    assert log["requestId"] == "req-1"
    assert log["requestTime"].endswith("Z")


def test_keeps_the_queue_without_a_token_and_sends_it_once_logged_in(connection, storage, config):
    sm = SessionManager(connection)  # not logged in yet
    up = CloudUploader(connection, sm, storage, config, start_worker=False)
    up.push(_msg(Severity.Info, "before login"))
    up.flush()
    assert _ingest_calls(connection) == []

    connection.when("auth/loginSdkServer", login_response())
    sm.login("app", "key")
    up.flush()
    assert _messages(connection) == ["before login"]
    sm.destroy()


def test_requeues_when_unreachable_or_on_a_server_error_but_not_on_a_4xx(uploader, connection):
    for status in (0, 503):
        connection.when("sessions/ingest", Response(ok=False, status=status, reason="err"))
        uploader.push(_msg(Severity.Info, f"keep-{status}"))
        uploader.flush()

    connection.when("sessions/ingest", Response(ok=True, status=200, reason="OK", data={}))
    connection.requests.clear()
    uploader.flush()
    assert _messages(connection) == ["keep-0", "keep-503"]

    connection.when("sessions/ingest", Response(ok=False, status=400, reason="bad"))
    uploader.push(_msg(Severity.Info, "rejected"))
    uploader.flush()
    connection.when("sessions/ingest", Response(ok=True, status=200, reason="OK", data={}))
    connection.requests.clear()
    uploader.flush()
    assert _ingest_calls(connection) == []


def test_exception_log_is_its_own_type_and_never_held(connection, session_manager, storage):
    up = CloudUploader(
        connection, session_manager, storage, config_with("Error"), start_worker=False
    )
    try:
        raise ValueError("bad value")
    except ValueError as error:
        up.push(ExceptionLog.from_exc_info(type(error), error, error.__traceback__))
    up.flush()

    log = connection.ingested_sessions()[0]["logs"][0]
    assert log["type"] == "exception"
    assert log["name"] == "ValueError"
    assert log["reason"] == "bad value"
    assert (
        log["stackTrace"][-1]["methodName"] == "test_exception_log_is_its_own_type_and_never_held"
    )


def test_keeps_the_cloud_queue_in_memory_with_nothing_on_disk(uploader, connection, tmp_path):
    uploader.push(_msg(Severity.Info, "memory"))
    uploader.flush()
    assert _messages(connection) == ["memory"]
    assert os.listdir(tmp_path) == ["machine_udid"]


# --- flushQueue: Accumulate, as on mobile -------------------------------------------------


def _accumulating(connection, session_manager, storage, **cloud):
    return CloudUploader(
        connection, session_manager, storage, config_with("Warning", **cloud), start_worker=False
    )


def test_holds_logs_below_flush_severity_so_a_quiet_request_uploads_only_its_session(
    connection, session_manager, storage
):
    up = _accumulating(connection, session_manager, storage)
    with context.run(RequestContext(session_id="quiet")):
        up.push(_msg(Severity.Info, "info"))
    up.flush()

    sessions = connection.ingested_sessions()
    assert [s["sessionId"] for s in sessions] == ["quiet"]
    assert sessions[0]["logs"] == []


def test_saves_held_logs_as_context_of_a_warning_keeping_the_last_flush_size(
    connection, session_manager, storage
):
    up = _accumulating(connection, session_manager, storage, flushSize=2)
    with context.run(RequestContext(session_id="failing")):
        for message in ("1", "2", "3"):
            up.push(_msg(Severity.Info, message))
        up.push(_msg(Severity.Warning, "warning"))
    up.flush()
    assert _messages(connection) == ["2", "3", "warning"]


def test_keeps_each_requests_flush_queue_apart(connection, session_manager, storage):
    up = _accumulating(connection, session_manager, storage)
    with context.run(RequestContext(session_id="a")):
        up.push(_msg(Severity.Info, "a info"))
    with context.run(RequestContext(session_id="b")):
        up.push(_msg(Severity.Error, "b error"))
    up.flush()
    assert _messages(connection) == ["b error"]


def test_uploads_request_events_only_around_a_logged_error(connection, session_manager, storage):
    up = _accumulating(connection, session_manager, storage)
    failing = RequestContext(session_id="failing", request_id="r1")
    with context.run(failing):
        start = RequestEvent(RequestEventPhase.Start, RequestKind.Http, "GET", "/orders")
        up.push(start)
        up.push(_msg(Severity.Error, "error"))
        up.push(
            RequestEvent(
                RequestEventPhase.End,
                RequestKind.Http,
                "GET",
                "/orders",
                None,
                failing.start_time,
                start.order_id,
                500,
            )
        )
    with context.run(RequestContext(session_id="healthy", request_id="r2")):
        up.push(RequestEvent(RequestEventPhase.Start, RequestKind.Http, "GET", "/health"))
        up.push(RequestEvent(RequestEventPhase.End, RequestKind.Http, "GET", "/health"))
    up.flush()

    logs = [log for s in connection.ingested_sessions() for log in s["logs"]]
    assert [log.get("event", log.get("message")) for log in logs] == ["start", "error", "end"]
    assert logs[2]["startOrderId"] == logs[0]["orderId"]


def test_saves_a_failed_request_with_its_start_even_when_it_logged_nothing(
    connection, session_manager, storage
):
    up = _accumulating(connection, session_manager, storage)
    with context.run(RequestContext(session_id="failed", request_id="r1")):
        up.push(RequestEvent(RequestEventPhase.Start, RequestKind.Http, "GET", "/orders"))
        up.push(
            RequestEvent(
                RequestEventPhase.End,
                RequestKind.Http,
                "GET",
                "/orders",
                status=500,
                outcome=RequestOutcome.Error,
            )
        )
    up.flush()

    logs = connection.ingested_sessions()[0]["logs"]
    assert [(log["event"], log.get("outcome")) for log in logs] == [
        ("start", None),
        ("end", "error"),
    ]


# --- Uploading: the timer, maxBatchSize and maxLogSize -------------------------------------


def _with_worker(connection, session_manager, storage, **cloud):
    return CloudUploader(connection, session_manager, storage, config_with(**cloud))


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    return predicate()


def test_sends_a_burst_of_errors_in_one_upload_when_the_timer_fires(
    connection, session_manager, storage
):
    up = _with_worker(connection, session_manager, storage, maxTime=0.1)
    for i in range(5):
        up.push(_msg(Severity.Error, f"error {i}"))
    assert _ingest_calls(connection) == []

    assert _wait_for(lambda: _ingest_calls(connection))
    time.sleep(0.15)
    assert len(_ingest_calls(connection)) == 1
    assert len(_messages(connection)) == 5
    up.shutdown(1)


def test_sends_before_the_timer_once_the_queue_reaches_max_batch_size(
    connection, session_manager, storage
):
    up = _with_worker(connection, session_manager, storage, maxTime=60, maxBatchSize=3)
    up.push(_msg(Severity.Info, "1"))  # the session and its log: 2
    time.sleep(0.05)
    assert _ingest_calls(connection) == []

    up.push(_msg(Severity.Info, "2"))
    assert _wait_for(lambda: _ingest_calls(connection))
    assert _messages(connection) == ["1", "2"]
    up.shutdown(1)


def test_empties_the_queue_at_max_log_size_while_it_cannot_upload(connection, storage):
    sm = SessionManager(connection)  # no token: nothing drains the queue
    up = CloudUploader(connection, sm, storage, config_with(maxLogSize=4), start_worker=False)
    for message in ("1", "2", "3", "4"):
        up.push(_msg(Severity.Info, message))

    connection.when("auth/loginSdkServer", login_response())
    sm.login("app", "key")
    up.flush()
    assert _messages(connection) == ["4"]
    sm.destroy()


def test_never_loses_a_log_while_threads_log_during_uploads(connection, session_manager, storage):
    up = _with_worker(connection, session_manager, storage, maxTime=0.01)

    def log_many(thread):
        with context.run(RequestContext(session_id=f"thread-{thread}")):
            for i in range(300):
                up.push(_msg(Severity.Info, f"{thread}-{i}"))

    threads = [threading.Thread(target=log_many, args=(t,)) for t in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    up.shutdown()

    messages = _messages(connection)
    assert len(messages) == 8 * 300
    assert len(set(messages)) == len(messages)
