from typing import Any, Callable, Optional

from starlette.requests import Request
from starlette.routing import Match

from .. import context as _context
from ..models.user import User
from ..request_events import HttpRequest, json_rpc_operation
from ._common import MAX_OPERATION_BODY, Extractors, json_body, request_context, request_metadata


class ShipbookMiddleware:
    """ASGI middleware for Starlette and FastAPI. Binds each request to a Shipbook session,
    so logs emitted while handling it carry the request's user, IP and trace id, and records
    the request's start and end (method, route, status, duration)::

        app.add_middleware(ShipbookMiddleware, user_extractor=lambda request: shipbook.User(...))

    A plain ASGI middleware, not BaseHTTPMiddleware: it doesn't buffer streaming responses,
    and it sees the status even when the endpoint raises.
    """

    def __init__(
        self,
        app,
        user_extractor: Optional[Callable[[Request], Optional[User]]] = None,
        session_extractor: Optional[Callable[[Request], Optional[str]]] = None,
        trace_extractor: Optional[Callable[[Request], Optional[str]]] = None,
        metadata_extractor: Optional[Callable[[Request], dict[str, Any]]] = None,
    ) -> None:
        self.app = app
        self._extractors = Extractors(
            user_extractor, session_extractor, trace_extractor, metadata_extractor
        )

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        ctx = request_context(request, self._extractors, request.headers.get)
        metadata = request_metadata(
            request,
            self._extractors,
            request.headers.get,
            request.url.path,
            request.client.host if request.client else None,
        )
        content_type = request.headers.get("content-type")
        body: list[bytes] = []
        body_size = 0
        status = 500
        ended = False

        # The body is captured as the endpoint reads it, so the middleware never consumes it.
        async def receive_body():
            nonlocal body_size
            message = await receive()
            if message["type"] == "http.request" and content_type and "json" in content_type:
                body_size += len(message.get("body", b""))
                if body_size <= MAX_OPERATION_BODY:
                    body.append(message.get("body", b""))
            return message

        def end() -> None:
            nonlocal ended
            if ended:
                return
            ended = True
            operation = json_rpc_operation(json_body(content_type, lambda: b"".join(body)))
            tracker.end(status, self._route(scope) or request.url.path, operation)

        async def send_status(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                end()

        tracker = HttpRequest(ctx, request.method, request.url.path, metadata=metadata)
        token = _context.set_context(ctx)
        try:
            await self.app(scope, receive_body, send_status)
        finally:
            _context.reset(token)
            end()

    @staticmethod
    def _route(scope) -> Optional[str]:
        # FastAPI puts the matched route in the scope; plain Starlette doesn't, so match it again.
        route = scope.get("route")
        if route is not None and getattr(route, "path", None):
            return route.path
        app = scope.get("app")
        routes = getattr(getattr(app, "router", app), "routes", None) or []
        for candidate in routes:
            match, _ = candidate.matches(scope)
            if match == Match.FULL:
                return getattr(candidate, "path", None)
        return None
