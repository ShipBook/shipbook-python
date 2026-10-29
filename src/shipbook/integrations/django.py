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
    override the ``get_*`` methods to attach the user, group requests, or add attributes.

    By default a request joins its Django session (``request.session.session_key``) when it
    has one, as the Node SDK joins an express-session.
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
        return None

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
        match = getattr(request, "resolver_match", None)
        route = "/" + match.route if match is not None and match.route else request.path
        small = int(request.META.get("CONTENT_LENGTH") or 0) <= MAX_OPERATION_BODY
        # request.body raises once a view streamed the body with read(): then there's no operation.
        operation = json_rpc_operation(
            json_body(request.content_type, lambda: request.body if small else b"")
        )
        tracker.end(status, route, operation)
