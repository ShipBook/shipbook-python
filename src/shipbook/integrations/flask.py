from typing import Any, Callable, Optional

from flask import g, request

from .. import context as _context
from ..models.user import User
from ..request_events import HttpRequest, json_rpc_operation
from ._common import MAX_OPERATION_BODY, Extractors, json_body, request_context, request_metadata

_TOKEN_KEY = "_shipbook_ctx_token"
_TRACKER_KEY = "_shipbook_request"
_STATUS_KEY = "_shipbook_status"


def init_app(
    app,
    user_extractor: Optional[Callable[[Any], Optional[User]]] = None,
    session_extractor: Optional[Callable[[Any], Optional[str]]] = None,
    trace_extractor: Optional[Callable[[Any], Optional[str]]] = None,
    metadata_extractor: Optional[Callable[[Any], dict[str, Any]]] = None,
) -> None:
    """Bind each Flask request to a Shipbook session and record its start and end::

    from shipbook.integrations.flask import init_app
    init_app(app)
    """
    extractors = Extractors(user_extractor, session_extractor, trace_extractor, metadata_extractor)

    def route() -> str:
        return request.url_rule.rule if request.url_rule else request.path

    @app.before_request
    def _shipbook_before():
        ctx = request_context(request, extractors, request.headers.get)
        metadata = request_metadata(
            request, extractors, request.headers.get, request.path, request.remote_addr
        )
        setattr(g, _TOKEN_KEY, _context.set_context(ctx))
        setattr(g, _TRACKER_KEY, HttpRequest(ctx, request.method, route(), metadata=metadata))

    @app.after_request
    def _shipbook_after(response):
        setattr(g, _STATUS_KEY, response.status_code)
        return response

    @app.teardown_request
    def _shipbook_teardown(exc):
        tracker = g.pop(_TRACKER_KEY, None)
        if tracker is not None:
            small = (request.content_length or 0) <= MAX_OPERATION_BODY
            operation = json_rpc_operation(
                json_body(
                    request.content_type, lambda: request.get_data(cache=True) if small else b""
                )
            )
            tracker.end(g.pop(_STATUS_KEY, 500 if exc else 200), route(), operation)
        token = g.pop(_TOKEN_KEY, None)
        if token is not None:
            _context.reset(token)
