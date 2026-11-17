import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Optional

from .._util import next_order_id, to_iso
from .frames import to_frames

# How many exceptions back a reason goes: enough for a real chain, short for a reason.
_MAX_CAUSES = 4


def stack_from_traceback(tb: Optional[TracebackType]) -> list[dict[str, Any]]:
    return to_frames(traceback.extract_tb(tb))


def reason_with_causes(exc: BaseException) -> str:
    """The exception's message, then what led to it. The wire has one exception per log, so a
    chain (``raise ... from ...``, or an exception raised while handling another) is spelled
    out here, the way Python prints it above the traceback."""
    reason = str(exc)
    seen = {id(exc)}
    for _ in range(_MAX_CAUSES):
        cause = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
        if cause is None or id(cause) in seen:
            break
        seen.add(id(cause))
        led = "caused by" if exc.__cause__ is not None else "while handling"
        reason = f"{reason} ({led} {type(cause).__name__}: {cause})".lstrip()
        exc = cause
    return reason


@dataclass
class ExceptionLog:
    """An uncaught exception, sent as its own log type (``exception``) like other SDKs' crashes."""

    name: str
    reason: str
    stack_trace: list[dict[str, Any]]
    thread_name: Optional[str] = field(default_factory=lambda: threading.current_thread().name)
    thread_id: Optional[int] = field(default_factory=threading.get_ident)
    order_id: int = field(default_factory=next_order_id)
    time: str = field(default_factory=lambda: to_iso(datetime.now(timezone.utc)))

    @classmethod
    def from_exc_info(
        cls,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: Optional[TracebackType],
    ) -> "ExceptionLog":
        return cls(exc_type.__name__, reason_with_causes(exc_value), stack_from_traceback(exc_tb))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "exception",
            "time": self.time,
            "orderId": self.order_id,
            "name": self.name,
            "reason": self.reason,
            "stackTrace": self.stack_trace,
            "threadInfo": {"threadName": self.thread_name, "threadId": self.thread_id},
        }
