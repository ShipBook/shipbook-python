import threading

import shipbook
from shipbook import context
from shipbook.models.message import Message
from shipbook.models.request_context import RequestContext
from shipbook.models.user import User
from shipbook.severity import Severity


def test_run_sets_and_resets():
    from shipbook.models.request_context import RequestContext

    assert context.get() is None
    with context.run(RequestContext(session_id="s1")):
        assert context.get().session_id == "s1"
    assert context.get() is None


def test_run_in_context_marks_background_and_runs_a_request():
    with shipbook.run_in_context(job_name="nightly", attributes={"k": "v"}) as ctx:
        active = context.get()
        assert active is ctx
        assert active.is_background is True
        assert active.job_name == "nightly"
        assert active.attributes == {"k": "v"}
        assert active.session_id
        assert active.request_id
    assert context.get() is None


def test_register_user_on_active_context():
    with shipbook.run_in_context(job_name="j"):
        context.register_user("u1", email="a@b.com")
        assert context.get().user.user_id == "u1"
        assert context.get().user.email == "a@b.com"


def _request(runtime, session_id="s1"):
    # What a framework middleware does when a request begins: the session is queued before any log.
    ctx = RequestContext(session_id=session_id, request_id="r1")
    runtime.uploader.start_request(ctx)
    return ctx


def test_register_user_in_a_request_reaches_its_session(active_runtime, connection):
    with context.run(_request(active_runtime)):
        context.register_user("u1", email="a@b.com")
        active_runtime.uploader.push(Message(severity=Severity.Info, message="hi", tag="t"))
    active_runtime.uploader.flush()

    (session,) = connection.ingested_sessions()
    assert session["userInfo"] == {"userId": "u1", "email": "a@b.com"}


def test_register_user_after_the_session_went_up_sends_the_user_alone(active_runtime, connection):
    with context.run(_request(active_runtime)):
        active_runtime.uploader.push(Message(severity=Severity.Info, message="hi", tag="t"))
        active_runtime.uploader.flush()
        context.register_user("u1")
    active_runtime.uploader.flush()

    first, second = connection.ingested_sessions()
    assert "userInfo" not in first
    assert (second["sessionId"], second["userInfo"]) == ("s1", {"userId": "u1"})
    assert (second["logs"], second["requests"]) == ([], 0)


def test_register_user_in_a_job_reaches_its_session(active_runtime, connection):
    with shipbook.run_in_context("billing"):
        context.register_user("u1")
    active_runtime.uploader.flush()

    (session,) = connection.ingested_sessions()
    assert (session["jobName"], session["userInfo"]) == ("billing", {"userId": "u1"})


def test_a_user_known_from_a_later_request_of_the_session_is_sent(active_runtime, connection):
    _request(active_runtime, "login-session")
    signed_in = RequestContext(session_id="login-session", request_id="r2", user=User("u1"))
    active_runtime.uploader.start_request(signed_in)
    active_runtime.uploader.flush()

    (session,) = connection.ingested_sessions()
    assert (session["requests"], session["userInfo"]) == (2, {"userId": "u1"})


def test_register_user_no_context_is_noop():
    assert context.get() is None
    context.register_user("u1")  # must not raise
    assert context.get() is None


def test_preserve_context_carries_into_thread():
    from shipbook.models.request_context import RequestContext

    seen = {}

    def work():
        ctx = context.get()
        seen["session_id"] = ctx.session_id if ctx else None

    with context.run(RequestContext(session_id="carried")):
        wrapped = context.preserve_context(work)
    t = threading.Thread(target=wrapped)
    t.start()
    t.join()
    assert seen["session_id"] == "carried"


def test_plain_thread_does_not_inherit_context():
    from shipbook.models.request_context import RequestContext

    seen = {}

    def work():
        seen["ctx"] = context.get()

    with context.run(RequestContext(session_id="not-carried")):
        t = threading.Thread(target=work)
        t.start()
        t.join()
    assert seen["ctx"] is None
