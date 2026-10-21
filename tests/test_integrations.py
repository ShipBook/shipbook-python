import asyncio
import json
import sys

import pytest
from django.urls import path

from shipbook import context
from shipbook.models.message import Message
from shipbook.severity import Severity


def _log(runtime, text="handled"):
    # Request events go up only around a saved log, as in the Node SDK.
    runtime.uploader.push(Message(severity=Severity.Info, message=text, tag="test"))


def _sent(uploader, connection):
    uploader.flush()
    return connection.ingested_sessions()


def _request_events(sessions):
    return [log for s in sessions for log in s["logs"] if log["type"] == "requestEvent"]


def _starlette_app(routes, **middleware):
    from starlette.applications import Starlette

    from shipbook.integrations.fastapi import ShipbookMiddleware

    app = Starlette(routes=routes)
    app.add_middleware(ShipbookMiddleware, **middleware)
    return app


def test_starlette_binds_the_request_and_records_its_start_and_end(active_runtime, connection):
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    captured = {}

    async def endpoint(request):
        captured["ctx"] = context.get()
        _log(active_runtime)
        return PlainTextResponse("ok")

    client = TestClient(_starlette_app([Route("/items/{item_id}", endpoint)]))
    resp = client.get("/items/7", headers={"x-request-id": "req-42", "user-agent": "pytest"})
    assert resp.status_code == 200

    ctx = captured["ctx"]
    assert ctx.is_background is False
    assert ctx.trace_id == "req-42"
    assert ctx.request_id
    assert ctx.metadata["path"] == "/items/7"
    assert ctx.metadata["userAgent"] == "pytest"
    assert context.get() is None

    sessions = _sent(active_runtime.uploader, connection)
    assert [s["sessionId"] for s in sessions] == [ctx.session_id]
    start, end = _request_events(sessions)
    assert (start["event"], start["kind"], start["method"]) == ("start", "http", "GET")
    assert end["event"] == "end"
    assert end["route"] == "/items/{item_id}"
    assert (end["status"], end["outcome"]) == (200, "ok")
    assert end["startOrderId"] == start["orderId"]
    assert end["duration"] >= 0
    assert start["requestId"] == end["requestId"] == ctx.request_id


def test_starlette_saves_a_failed_request_even_when_it_logged_nothing(active_runtime, connection):
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def endpoint(request):
        raise RuntimeError("boom")

    client = TestClient(_starlette_app([Route("/fail", endpoint)]), raise_server_exceptions=False)
    assert client.get("/fail").status_code == 500

    start, end = _request_events(_sent(active_runtime.uploader, connection))
    assert start["event"] == "start"
    assert (end["status"], end["outcome"]) == (500, "error")


def test_starlette_labels_a_json_rpc_call_with_its_operation(active_runtime, connection):
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def mcp(request):
        _log(active_runtime)
        return JSONResponse({"jsonrpc": "2.0", "id": 1, "result": await request.json()})

    client = TestClient(_starlette_app([Route("/mcp", mcp, methods=["POST"])]))
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get-logs"}}
    assert client.post("/mcp", json=body).json()["result"] == body

    end = _request_events(_sent(active_runtime.uploader, connection))[-1]
    assert end["operation"] == "tools/call get-logs"


def test_starlette_joins_the_callers_session_and_uses_the_extractors(active_runtime, connection):
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import shipbook

    captured = {}

    async def endpoint(request):
        captured["ctx"] = context.get()
        return PlainTextResponse("ok")

    app = _starlette_app(
        [Route("/hi", endpoint)],
        user_extractor=lambda request: shipbook.User(user_id="u1"),
        metadata_extractor=lambda request: {"tenant": "acme"},
    )
    TestClient(app).get("/hi", headers={"x-shipbook-session": "1:client-app:client-sess"})

    ctx = captured["ctx"]
    assert ctx.session_id == ctx.caller_session_link == "1:client-app:client-sess"
    assert ctx.user.user_id == "u1"
    assert ctx.metadata["tenant"] == "acme"
    session = _sent(active_runtime.uploader, connection)[0]
    assert session["callerSessionLink"] == "1:client-app:client-sess"


def test_flask_binds_the_request_and_records_its_route_and_status(active_runtime, connection):
    from flask import Flask

    from shipbook.integrations.flask import init_app

    captured = {}
    app = Flask(__name__)
    init_app(app, session_extractor=lambda request: request.headers.get("x-login"))

    @app.route("/items/<int:item_id>")
    def item(item_id):
        captured["ctx"] = context.get()
        _log(active_runtime)
        return "missing", 404

    resp = app.test_client().get("/items/3", headers={"x-correlation-id": "c-9", "x-login": "L1"})
    assert resp.status_code == 404

    ctx = captured["ctx"]
    assert ctx.trace_id == "c-9"
    assert ctx.session_id == "L1"
    assert context.get() is None
    start, end = _request_events(_sent(active_runtime.uploader, connection))
    assert start["route"] == end["route"] == "/items/<int:item_id>"
    # A 4xx is the client's mistake, not a failed request.
    assert (end["status"], end["outcome"]) == (404, "ok")


def test_flask_labels_a_json_rpc_call_with_its_operation(active_runtime, connection):
    from flask import Flask, request

    from shipbook.integrations.flask import init_app

    app = Flask(__name__)
    init_app(app)

    @app.post("/mcp")
    def mcp():
        _log(active_runtime)
        return {"echo": [call["method"] for call in request.get_json()]}

    body = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "method": "ping"},
    ]
    app.test_client().post("/mcp", json=body)

    end = _request_events(_sent(active_runtime.uploader, connection))[-1]
    assert end["operation"] == "tools/list, ping"


@pytest.fixture
def django_setup():
    from django.conf import settings

    if not settings.configured:
        settings.configure(DEBUG=True, ALLOWED_HOSTS=["*"])
    import django

    django.setup()


def _django_view(request, item_id):
    from django.http import JsonResponse

    request.runtime.uploader.push(Message(severity=Severity.Info, message="handled", tag="test"))
    return JsonResponse({"ctx_request_id": context.get().request_id})


urlpatterns = [path("items/<int:item_id>", _django_view)]


def test_django_binds_the_request_and_records_its_route(active_runtime, connection, django_setup):
    from django.test import RequestFactory
    from django.urls import resolve

    from shipbook.integrations.django import ShipbookMiddleware

    def get_response(request):
        request.resolver_match = resolve(request.path, urlconf=sys.modules[__name__])
        return request.resolver_match.func(request, **request.resolver_match.kwargs)

    request = RequestFactory().get("/items/5", HTTP_X_REQUEST_ID="dj-7", HTTP_USER_AGENT="pytest")
    request.runtime = active_runtime
    response = ShipbookMiddleware(get_response)(request)
    request_id = json.loads(response.content)["ctx_request_id"]

    assert context.get() is None
    start, end = _request_events(_sent(active_runtime.uploader, connection))
    assert start["requestId"] == end["requestId"] == request_id
    assert end["route"] == "/items/<int:item_id>"
    assert (end["status"], end["outcome"]) == (200, "ok")


def test_django_async_view_and_a_raised_error(active_runtime, connection, django_setup):
    from django.test import RequestFactory

    from shipbook.integrations.django import ShipbookMiddleware

    async def get_response(request):
        assert context.get() is not None
        raise RuntimeError("boom")

    middleware = ShipbookMiddleware(get_response)
    assert asyncio.iscoroutinefunction(middleware)
    with pytest.raises(RuntimeError):
        asyncio.run(middleware(RequestFactory().post("/fail")))

    end = _request_events(_sent(active_runtime.uploader, connection))[-1]
    assert (end["method"], end["status"], end["outcome"]) == ("POST", 500, "error")
