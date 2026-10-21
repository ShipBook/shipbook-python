import dataclasses
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import _state
from . import context as _context
from .models.request_context import RequestContext
from .models.request_event import RequestEvent, RequestEventPhase, RequestKind, RequestOutcome


def _push(ctx: RequestContext, event: RequestEvent) -> None:
    runtime = _state.get_active()
    if runtime is None:
        return

    def push() -> None:
        with _context.run(ctx):
            runtime.uploader.push(event)

    runtime.when_configured(push)


def json_rpc_operation(body: Any) -> Optional[str]:
    """MCP (any JSON-RPC) multiplexes every call on one endpoint; the method and its
    tool/prompt/resource tell the calls apart, e.g. ``tools/call get-logs``."""
    calls = body if isinstance(body, list) else [body]
    operations = []
    for call in calls:
        if (
            not isinstance(call, dict)
            or call.get("jsonrpc") != "2.0"
            or not isinstance(call.get("method"), str)
        ):
            continue
        params = call.get("params")
        target = params.get("name", params.get("uri")) if isinstance(params, dict) else None
        operations.append(
            f"{call['method']} {target}" if isinstance(target, str) else call["method"]
        )
    return ", ".join(operations) or None


class HttpRequest:
    """One HTTP request's start and end events. Create it inside the request's context;
    routing and body parsing may only be done by the end, so the end takes them again."""

    def __init__(
        self, ctx: RequestContext, method: str, route: str, operation: Optional[str] = None
    ) -> None:
        self._ctx = ctx
        self._method = method
        self._start = RequestEvent(
            RequestEventPhase.Start, RequestKind.Http, method, route, operation
        )
        _push(ctx, self._start)

    def end(self, status: int, route: str, operation: Optional[str] = None) -> None:
        # As for an HTTP server span: a 4xx is the client's mistake, only a 5xx failed the request.
        outcome = RequestOutcome.Error if status >= 500 else RequestOutcome.Ok
        _push(
            self._ctx,
            RequestEvent(
                RequestEventPhase.End,
                RequestKind.Http,
                self._method,
                route,
                operation,
                self._ctx.start_time,
                self._start.order_id,
                status,
                outcome,
                _elapsed_ms(self._ctx),
            ),
        )


def _elapsed_ms(ctx: RequestContext) -> int:
    return int((datetime.now(timezone.utc) - ctx.start_time).total_seconds() * 1000)


def open_request(
    session: RequestContext, kind: RequestKind, operation: Optional[str] = None
) -> tuple[RequestContext, Callable[[RequestOutcome, Optional[int]], None]]:
    """A request without HTTP (an MCP call over stdio, a queue message) inside the given
    session; the returned ``end(outcome, error_code)`` writes how it finished."""
    ctx = dataclasses.replace(
        session, request_id=str(uuid.uuid4()), start_time=datetime.now(timezone.utc)
    )
    start = RequestEvent(RequestEventPhase.Start, kind, operation=operation)
    _push(ctx, start)

    def end(outcome: RequestOutcome, error_code: Optional[int] = None) -> None:
        _push(
            ctx,
            RequestEvent(
                RequestEventPhase.End,
                kind,
                None,
                None,
                operation,
                ctx.start_time,
                start.order_id,
                None,
                outcome,
                _elapsed_ms(ctx),
                error_code,
            ),
        )

    return ctx, end


@contextmanager
def run_in_request(kind: RequestKind, operation: str) -> Iterator[RequestContext]:
    """Runs the block as one request of the current session (the process's background
    session outside any), ending with how the block finishes::

        with shipbook.run_in_request(shipbook.RequestKind.Rpc, "process order"):
            process(order)
    """
    runtime = _state.get_active()
    session = _context.get() or (runtime.uploader.background_context if runtime else None)
    if session is None:
        session = RequestContext(session_id=str(uuid.uuid4()), is_background=True)
    ctx, end = open_request(session, kind, operation)
    try:
        with _context.run(ctx):
            yield ctx
    except BaseException:
        end(RequestOutcome.Error, None)
        raise
    end(RequestOutcome.Ok, None)
