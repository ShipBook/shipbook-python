import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Generic, Optional, TypeVar

from .. import _state
from ..handler import ShipbookHandler
from ..models.attributes import Attributes
from ..models.frames import in_app
from ..models.request_context import RequestContext
from ..models.request_event import RequestEvent, RequestEventPhase, RequestKind
from ..models.user import User

SESSION_LINK_HEADER = "x-shipbook-session"
# Only a JSON body this small is parsed for its JSON-RPC operation (MCP over HTTP).
MAX_OPERATION_BODY = 1024 * 1024

R = TypeVar("R")

# Its own handler and no propagation: the server already prints the traceback, this only sends it.
_unhandled_log = logging.getLogger("shipbook.unhandled")
_unhandled_log.propagate = False
_unhandled_log.setLevel(logging.ERROR)
_unhandled_log.addHandler(ShipbookHandler())


@dataclass
class Extractors(Generic[R]):
    """Per-request hooks, as in the Node SDK's middleware. Each gets the framework's request."""

    user: Optional[Callable[[R], Optional[User]]] = None
    # Groups requests into one session (e.g. a login session); by default each is its own.
    session: Optional[Callable[[R], Optional[str]]] = None
    trace: Optional[Callable[[R], Optional[str]]] = None
    # The app's own facts about the request, stored on its start event.
    attributes: Optional[Callable[[R], Attributes]] = None


def trace_from_headers(get: Callable[[str], Optional[str]]) -> Optional[str]:
    """First of traceparent / x-request-id / x-correlation-id, via a ``get(name)`` accessor."""
    for name in ("traceparent", "x-request-id", "x-correlation-id"):
        value = get(name)
        if value:
            return value
    return None


def request_context(
    request: R,
    extractors: Extractors[R],
    header: Callable[[str], Optional[str]],
) -> RequestContext:
    caller_session_link = header(SESSION_LINK_HEADER)
    session_id = extractors.session(request) if extractors.session else None
    ctx = RequestContext(
        # A linked request joins its caller's session: every server session has one caller.
        session_id=caller_session_link or session_id or str(uuid.uuid4()),
        trace_id=(extractors.trace(request) if extractors.trace else None)
        or trace_from_headers(header),
        request_id=str(uuid.uuid4()),
        caller_session_link=caller_session_link,
        user=extractors.user(request) if extractors.user else None,
        is_background=False,
    )
    runtime = _state.get_active()
    if runtime is not None:
        runtime.when_configured(lambda: runtime.uploader.start_request(ctx))
    return ctx


def request_start(
    request: R,
    extractors: Extractors[R],
    header: Callable[[str], Optional[str]],
    method: str,
    route: str,
    path: str,
    ip: Optional[str],
) -> RequestEvent:
    return RequestEvent(
        RequestEventPhase.Start,
        RequestKind.Http,
        method,
        route,
        path=path,
        ip=ip,
        user_agent=header("user-agent"),
        attributes=(extractors.attributes(request) if extractors.attributes else None) or None,
    )


def json_body(content_type: Optional[str], read: Callable[[], bytes]) -> Any:
    if not content_type or "json" not in content_type:
        return None
    try:
        raw = read()
        return json.loads(raw) if raw and len(raw) <= MAX_OPERATION_BODY else None
    except Exception:  # noqa: BLE001 — an unreadable body just has no operation
        return None


def record_unhandled(error: Exception, operation: str) -> None:
    """An exception the framework lets through without logging it (Starlette, FastAPI): sent as
    an error of the current request, from the innermost line of the app's own code."""
    entries = []
    tb = error.__traceback__
    while tb is not None:
        entries.append(tb)
        tb = tb.tb_next
    own = [entry for entry in entries if in_app(entry.tb_frame.f_code.co_filename)]
    at = (own or entries)[-1]
    code = at.tb_frame.f_code
    _unhandled_log.handle(
        _unhandled_log.makeRecord(
            at.tb_frame.f_globals.get("__name__", _unhandled_log.name),
            logging.ERROR,
            code.co_filename,
            at.tb_lineno,
            "Unhandled exception in %s",
            (operation,),
            (type(error), error, error.__traceback__),
            func=code.co_name,
        )
    )
