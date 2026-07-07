from shipbook import context


def _session_records(uploader):
    records = uploader._storage.pop_all_array_obj("session_queue")
    return [r for r in records if r.get("type") == "session"]


def test_fastapi_middleware_binds_context(active_runtime):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from shipbook.integrations.fastapi import ShipbookMiddleware

    captured = {}

    async def endpoint(request):
        captured["ctx"] = context.get()
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/hi", endpoint)])
    app.add_middleware(ShipbookMiddleware)

    client = TestClient(app)
    resp = client.get("/hi", headers={"x-request-id": "req-42", "user-agent": "pytest"})
    assert resp.status_code == 200

    ctx = captured["ctx"]
    assert ctx is not None
    assert ctx.is_background is False
    assert ctx.trace_id == "req-42"
    assert ctx.metadata["path"] == "/hi"
    assert ctx.metadata["userAgent"] == "pytest"
    # ensure_session registered the session up front
    assert any(r["sessionId"] == ctx.session_id for r in _session_records(active_runtime.uploader))
    # context cleaned up after the request
    assert context.get() is None


def test_flask_integration_binds_context(active_runtime):
    from flask import Flask

    from shipbook.integrations.flask import init_app

    captured = {}
    app = Flask(__name__)
    init_app(app)

    @app.route("/hi")
    def hi():
        captured["ctx"] = context.get()
        return "ok"

    client = app.test_client()
    resp = client.get("/hi", headers={"x-correlation-id": "corr-9"})
    assert resp.status_code == 200

    ctx = captured["ctx"]
    assert ctx.is_background is False
    assert ctx.trace_id == "corr-9"
    assert ctx.metadata["path"] == "/hi"
    assert any(r["sessionId"] == ctx.session_id for r in _session_records(active_runtime.uploader))
    assert context.get() is None


def test_django_middleware_binds_context(active_runtime):
    from django.conf import settings

    if not settings.configured:
        settings.configure(DEBUG=True, ALLOWED_HOSTS=["*"])
    import django

    django.setup()
    from django.test import RequestFactory

    from shipbook.integrations.django import ShipbookMiddleware

    captured = {}

    def get_response(request):
        captured["ctx"] = context.get()

        class R:
            status_code = 200

        return R()

    mw = ShipbookMiddleware(get_response)
    request = RequestFactory().get("/hi", HTTP_X_REQUEST_ID="dj-7", HTTP_USER_AGENT="pytest")
    mw(request)

    ctx = captured["ctx"]
    assert ctx.is_background is False
    assert ctx.trace_id == "dj-7"
    assert ctx.metadata["path"] == "/hi"
    assert ctx.metadata["userAgent"] == "pytest"
    assert any(r["sessionId"] == ctx.session_id for r in _session_records(active_runtime.uploader))
    assert context.get() is None
