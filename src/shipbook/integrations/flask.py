import uuid
from typing import Callable, Optional

from flask import g, request

from .. import context as _context
from ..models.request_context import RequestContext
from ..models.user import User
from ._common import ensure_session, trace_from_headers

_TOKEN_KEY = "_shipbook_ctx_token"


def init_app(app, user_extractor: Optional[Callable[[object], Optional[User]]] = None) -> None:
    """Bind each Flask request to a Shipbook session::

        from shipbook.integrations.flask import init_app
        init_app(app)
    """

    @app.before_request
    def _shipbook_before():
        ctx = RequestContext(
            session_id=str(uuid.uuid4()),
            trace_id=trace_from_headers(request.headers.get),
            user=user_extractor(request) if user_extractor else None,
            metadata={
                "method": request.method,
                "path": request.path,
                "ip": request.remote_addr,
                "userAgent": request.headers.get("user-agent"),
            },
            is_background=False,
        )
        ensure_session(ctx)
        setattr(g, _TOKEN_KEY, _context.set_context(ctx))

    @app.teardown_request
    def _shipbook_teardown(_exc):
        token = g.pop(_TOKEN_KEY, None)
        if token is not None:
            _context.reset(token)
