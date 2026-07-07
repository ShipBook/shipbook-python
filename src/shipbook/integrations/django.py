import uuid
from typing import Optional

from .. import context as _context
from ..models.request_context import RequestContext
from ..models.user import User
from ._common import ensure_session, trace_from_headers


class ShipbookMiddleware:
    """Django middleware. Add ``"shipbook.integrations.django.ShipbookMiddleware"``
    to ``MIDDLEWARE``. Subclass and override :meth:`get_user` to attach the
    authenticated user."""

    def __init__(self, get_response):
        self.get_response = get_response

    def get_user(self, request) -> Optional[User]:
        return None

    def __call__(self, request):
        meta = request.META
        ctx = RequestContext(
            session_id=str(uuid.uuid4()),
            trace_id=trace_from_headers(
                lambda name: meta.get("HTTP_" + name.upper().replace("-", "_"))
            ),
            user=self.get_user(request),
            metadata={
                "method": request.method,
                "path": request.path,
                "ip": meta.get("REMOTE_ADDR"),
                "userAgent": meta.get("HTTP_USER_AGENT"),
            },
            is_background=False,
        )
        ensure_session(ctx)
        with _context.run(ctx):
            return self.get_response(request)
