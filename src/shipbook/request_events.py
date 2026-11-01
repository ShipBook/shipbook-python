import dataclasses
import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import _state
from . import context as _context
from .models.attributes import Attributes
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
    """One HTTP request's start and end events. Create it inside the request's context with
    its start; routing and body parsing may only be done by the end, so the end takes them again."""

    def __init__(self, ctx: RequestContext, start: RequestEvent) -> None:
        self._ctx = ctx
        self._start = start
        _push(ctx, start)

    def end(self, status: int, route: str, operation: Optional[str] = None) -> None:
        # As for an HTTP server span: a 4xx is the client's mistake, only a 5xx failed the request.
        outcome = RequestOutcome.Error if status >= 500 else RequestOutcome.Ok
        _push(
            self._ctx, _end_request_event(self._start, self._ctx, route, operation, status, outcome)
        )


def _end_request_event(
    start: RequestEvent,
    ctx: RequestContext,
    route: Optional[str],
    operation: Optional[str],
    status: Optional[int],
    outcome: RequestOutcome,
    error_code: Optional[int] = None,
) -> RequestEvent:
    """The end repeats the start's facts, with the route and operation as known once it is done."""
    return RequestEvent(
        RequestEventPhase.End,
        start.kind,
        start.method,
        route,
        operation,
        ctx.start_time,
        start.order_id,
        status,
        outcome,
        _elapsed_ms(ctx),
        error_code,
        path=start.path,
        ip=start.ip,
        user_agent=start.user_agent,
        attributes=start.attributes,
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
    runtime = _state.get_active()
    if runtime is not None:
        runtime.when_configured(lambda: runtime.uploader.start_request(ctx))
    start = RequestEvent(RequestEventPhase.Start, kind, operation=operation)
    _push(ctx, start)

    def end(outcome: RequestOutcome, error_code: Optional[int] = None) -> None:
        _push(ctx, _end_request_event(start, ctx, None, operation, None, outcome, error_code))

    return ctx, end


@contextmanager
def _run_request(
    session: RequestContext, kind: RequestKind, operation: str
) -> Iterator[RequestContext]:
    ctx, end = open_request(session, kind, operation)
    try:
        with _context.run(ctx):
            yield ctx
    except BaseException:
        end(RequestOutcome.Error, None)
        raise
    end(RequestOutcome.Ok, None)


def run_in_request(kind: RequestKind, operation: str) -> AbstractContextManager[RequestContext]:
    """Runs the block as one request of the current session (the process's background
    session outside any), ending with how the block finishes::

        with shipbook.run_in_request(shipbook.RequestKind.Rpc, "process order"):
            process(order)
    """
    runtime = _state.get_active()
    session = _context.get() or (runtime.uploader.background_context if runtime else None)
    if session is None:
        session = RequestContext(session_id=str(uuid.uuid4()), is_background=True)
    return _run_request(session, kind, operation)


def run_job(
    job_name: str, attributes: Optional[Attributes] = None
) -> AbstractContextManager[RequestContext]:
    """Runs the block as a job run: its own session, run as one request of kind Job, so it
    is counted like an HTTP request and its start and end carry the job name, the duration
    and whether it raised::

        with shipbook.run_in_context("nightly-billing"):
            charge_customers()
    """
    session = RequestContext(
        session_id=str(uuid.uuid4()), attributes=attributes, is_background=True, job_name=job_name
    )
    return _run_request(session, RequestKind.Job, job_name)
