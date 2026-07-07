from typing import Optional

from .. import _state
from ..models.request_context import RequestContext


def trace_from_headers(get) -> Optional[str]:
    """First of traceparent / x-request-id / x-correlation-id, via a
    ``get(name) -> Optional[str]`` accessor."""
    for name in ("traceparent", "x-request-id", "x-correlation-id"):
        value = get(name)
        if value:
            return value
    return None


def ensure_session(ctx: RequestContext) -> None:
    """Register the session up front so requests that only log below the
    flush-severity still appear on the server."""
    runtime = _state.get_active()
    if runtime is not None:
        runtime.uploader.ensure_session(ctx)
