import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Generic, Optional, TypeVar

from .. import _state
from ..models.request_context import RequestContext
from ..models.user import User

SESSION_LINK_HEADER = "x-shipbook-session"
# Only a JSON body this small is parsed for its JSON-RPC operation (MCP over HTTP).
MAX_OPERATION_BODY = 1024 * 1024

R = TypeVar("R")


@dataclass
class Extractors(Generic[R]):
    """Per-request hooks, as in the Node SDK's middleware. Each gets the framework's request."""

    user: Optional[Callable[[R], Optional[User]]] = None
    # Groups requests into one session (e.g. a login session); by default each is its own.
    session: Optional[Callable[[R], Optional[str]]] = None
    trace: Optional[Callable[[R], Optional[str]]] = None
    metadata: Optional[Callable[[R], dict[str, Any]]] = None


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
    method: str,
    path: str,
    ip: Optional[str],
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
        metadata={
            "method": method,
            "path": path,
            "ip": ip,
            "userAgent": header("user-agent"),
            **(extractors.metadata(request) if extractors.metadata else {}),
        },
        is_background=False,
    )
    runtime = _state.get_active()
    if runtime is not None:
        runtime.when_configured(lambda: runtime.uploader.start_request(ctx))
    return ctx


def json_body(content_type: Optional[str], read: Callable[[], bytes]) -> Any:
    if not content_type or "json" not in content_type:
        return None
    try:
        raw = read()
        return json.loads(raw) if raw and len(raw) <= MAX_OPERATION_BODY else None
    except Exception:  # noqa: BLE001 — an unreadable body just has no operation
        return None
