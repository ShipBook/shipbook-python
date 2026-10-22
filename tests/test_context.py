import threading

import shipbook
from shipbook import context


def test_run_sets_and_resets():
    from shipbook.models.request_context import RequestContext

    assert context.get() is None
    with context.run(RequestContext(session_id="s1")):
        assert context.get().session_id == "s1"
    assert context.get() is None


def test_run_in_context_marks_background_and_runs_a_request():
    with shipbook.run_in_context(job_name="nightly", metadata={"k": "v"}) as ctx:
        active = context.get()
        assert active is ctx
        assert active.is_background is True
        assert active.job_name == "nightly"
        assert active.metadata == {"k": "v"}
        assert active.session_id
        assert active.request_id
    assert context.get() is None


def test_register_user_on_active_context():
    with shipbook.run_in_context(job_name="j"):
        context.register_user("u1", email="a@b.com")
        assert context.get().user.user_id == "u1"
        assert context.get().user.email == "a@b.com"


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
