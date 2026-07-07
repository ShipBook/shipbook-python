import contextvars
import functools
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Callable, Optional

from .models.request_context import RequestContext
from .models.user import User

_ctx: contextvars.ContextVar[Optional[RequestContext]] = contextvars.ContextVar(
    "shipbook_request_context", default=None
)


def get() -> Optional[RequestContext]:
    return _ctx.get()


def set_context(context: RequestContext) -> contextvars.Token:
    return _ctx.set(context)


def reset(token: contextvars.Token) -> None:
    _ctx.reset(token)


@contextmanager
def run(context: RequestContext) -> Iterator[RequestContext]:
    token = _ctx.set(context)
    try:
        yield context
    finally:
        _ctx.reset(token)


@contextmanager
def run_job(
    job_name: str, metadata: Optional[dict[str, Any]] = None
) -> Iterator[RequestContext]:
    context = RequestContext(
        session_id=str(uuid.uuid4()),
        metadata=metadata,
        is_background=True,
        job_name=job_name,
    )
    with run(context) as c:
        yield c


def preserve_context(fn: Callable) -> Callable:
    """Wrap ``fn`` so it runs with the *current* Shipbook context even when
    executed on another thread. Use when handing work to ``threading.Thread``
    or an executor, which otherwise start with a fresh (background) context::

        pool.submit(shipbook.preserve_context(do_work))
    """
    ctx = contextvars.copy_context()

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return ctx.run(fn, *args, **kwargs)

    return wrapper


def register_user(
    user_id: str,
    user_name: Optional[str] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
    additional_info: Optional[dict[str, str]] = None,
) -> None:
    """Attach user info to the current context (request or job). No-op with a
    warning path is avoided: if there is no active context, the user is dropped
    because a background/fallback session has no single owning user."""
    context = _ctx.get()
    if context is None:
        return
    context.user = User(
        user_id=user_id,
        user_name=user_name,
        full_name=full_name,
        email=email,
        phone_number=phone_number,
        additional_info=additional_info,
    )
