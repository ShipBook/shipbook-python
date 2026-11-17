from typing import Optional

from asgiref.sync import iscoroutinefunction, markcoroutinefunction

from .. import context as _context
from ..models.attributes import Attributes
from ..models.request_context import RequestContext
from ..models.user import User
from ..request_events import HttpRequest, json_rpc_operation
from ._common import MAX_OPERATION_BODY, Extractors, json_body, request_context, request_start


class ShipbookMiddleware:
    """Django middleware (sync and async). Add ``"shipbook.integrations.django.ShipbookMiddleware"``
    to ``MIDDLEWARE``, after ``SessionMiddleware`` and ``AuthenticationMiddleware``. Subclass and
    override the ``get_*`` methods to attach another user, group requests, or add attributes.

    By default a request joins its Django session (``request.session.session_key``) when it
    has one, and carries the signed-in Django user, as the Node SDK joins an express-session
    and picks up ``req.user``.
    """

    sync_capable = True
    async_capable = True

    def __init__(self, get_response) -> None:
        self.get_response = get_response
        self._async = iscoroutinefunction(get_response)
        if self._async:
            markcoroutinefunction(self)
        self._extractors = Extractors(
            self.get_user, self.get_session_id, self.get_trace_id, self.get_attributes
        )

    def get_user(self, request) -> Optional[User]:
        """The signed-in Django user, once the view has read ``request.user``: reading it here
        would cost every request a session and a database query. Asked when the request
        begins and, without an answer, again when it ends. Return ``None`` to attach no user."""
        user = getattr(request, "_cached_user", None) or getattr(request, "_acached_user", None)
        if user is None or not user.is_authenticated:
            return None
        return User(
            user_id=str(user.pk),
            user_name=user.get_username(),
            email=getattr(user, "email", None) or None,
        )

    def get_session_id(self, request) -> Optional[str]:
        session = getattr(request, "session", None)
        return getattr(session, "session_key", None)

    def get_trace_id(self, request) -> Optional[str]:
        return None

    def get_attributes(self, request) -> Attributes:
        return {}

    def __call__(self, request):
        if self._async:
            return self._acall(request)
        ctx, tracker = self._start(request)
        with _context.run(ctx):
            try:
                response = self.get_response(request)
            except BaseException:
                self._end(request, tracker, 500)
                raise
        self._end(request, tracker, response.status_code)
        return response

    async def _acall(self, request):
        ctx, tracker = self._start(request)
        with _context.run(ctx):
            try:
                response = await self.get_response(request)
            except BaseException:
                self._end(request, tracker, 500)
                raise
        self._end(request, tracker, response.status_code)
        return response

    def _start(self, request) -> tuple[RequestContext, HttpRequest]:
        meta = request.META

        def header(name: str) -> Optional[str]:
            return meta.get("HTTP_" + name.upper().replace("-", "_"))

        ctx = request_context(request, self._extractors, header)
        # Django logs a 4xx after this middleware has returned: the handler finds the request here.
        request.shipbook_context = ctx
        start = request_start(
            request,
            self._extractors,
            header,
            request.method,
            request.path,
            request.path,
            meta.get("REMOTE_ADDR"),
        )
        return ctx, HttpRequest(ctx, start)

    def _end(self, request, tracker: HttpRequest, status: int) -> None:
        ctx = request.shipbook_context
        user = None if ctx.user else self.get_user(request)
        if user is not None:
            _context.set_user(ctx, user)
        match = getattr(request, "resolver_match", None)
        route = "/" + match.route if match is not None and match.route else request.path
        small = int(request.META.get("CONTENT_LENGTH") or 0) <= MAX_OPERATION_BODY
        # request.body raises once a view streamed the body with read(): then there's no operation.
        operation = json_rpc_operation(
            json_body(request.content_type, lambda: request.body if small else b"")
        )
        tracker.end(status, route, operation)
