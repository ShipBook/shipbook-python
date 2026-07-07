import uuid
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware

from .. import context as _context
from ..models.request_context import RequestContext
from ..models.user import User
from ._common import ensure_session, trace_from_headers


class ShipbookMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware. Binds each request to a Shipbook session so
    logs emitted while handling it carry the request's user, IP, and trace id.

    Pass ``user_extractor=lambda request: shipbook.User(...)`` to attach the
    authenticated user.
    """

    def __init__(self, app, user_extractor: Optional[Callable[[object], Optional[User]]] = None):
        super().__init__(app)
        self._user_extractor = user_extractor

    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else None
        ctx = RequestContext(
            session_id=str(uuid.uuid4()),
            trace_id=trace_from_headers(request.headers.get),
            user=self._user_extractor(request) if self._user_extractor else None,
            metadata={
                "method": request.method,
                "path": request.url.path,
                "ip": client_ip,
                "userAgent": request.headers.get("user-agent"),
            },
            is_background=False,
        )
        ensure_session(ctx)
        token = _context.set_context(ctx)
        try:
            return await call_next(request)
        finally:
            _context.reset(token)
