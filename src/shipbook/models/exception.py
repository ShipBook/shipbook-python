import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Optional

from .._util import next_order_id, to_iso


def stack_from_traceback(tb: Optional[TracebackType]) -> list[dict[str, Any]]:
    return [
        {"methodName": frame.name, "fileName": frame.filename, "lineNumber": frame.lineno}
        for frame in traceback.extract_tb(tb)
    ]


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
        return cls(exc_type.__name__, str(exc_value), stack_from_traceback(exc_tb))

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
