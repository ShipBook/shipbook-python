import logging
import os
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .._util import next_order_id, to_iso
from ..severity import Severity


def _stack_from_tb(tb) -> list[dict[str, Any]]:
    return [
        {
            "methodName": frame.name,
            "fileName": frame.filename,
            "lineNumber": frame.lineno,
        }
        for frame in traceback.extract_tb(tb)
    ]


def _current_stack(skip_filename_fragments) -> list[dict[str, Any]]:
    """The caller's stack with logging-machinery and SDK frames trimmed out."""
    out: list[dict[str, Any]] = []
    for frame in traceback.extract_stack():
        if any(fragment in frame.filename for fragment in skip_filename_fragments):
            continue
        out.append(
            {
                "methodName": frame.name,
                "fileName": frame.filename,
                "lineNumber": frame.lineno,
            }
        )
    return out


_LOGGING_DIR = os.path.dirname(logging.__file__)
_SDK_DIR = os.path.dirname(os.path.dirname(__file__))


@dataclass
class Message:
    severity: Severity
    message: str
    tag: str
    function: str = ""
    file_name: str = ""
    line_number: int = 0
    thread_name: Optional[str] = None
    thread_id: Optional[int] = None
    exception: Optional[dict[str, Any]] = None
    stack_trace: Optional[list[dict[str, Any]]] = None
    order_id: int = field(default_factory=next_order_id)
    time: str = field(default_factory=lambda: to_iso(datetime.now(timezone.utc)))

    @classmethod
    def from_record(
        cls, record: logging.LogRecord, severity: Severity, include_stack: bool
    ) -> "Message":
        msg = cls(
            severity=severity,
            message=record.getMessage(),
            tag=record.name,
            function=record.funcName or "",
            file_name=record.pathname or "",
            line_number=record.lineno or 0,
            thread_name=record.threadName,
            thread_id=record.thread,
            time=to_iso(datetime.fromtimestamp(record.created, tz=timezone.utc)),
        )

        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            stack = _stack_from_tb(exc_tb)
            msg.exception = {
                "name": exc_type.__name__,
                "reason": str(exc_value),
                "stackTrace": stack,
            }
            msg.stack_trace = stack
        elif include_stack:
            msg.stack_trace = _current_stack((_LOGGING_DIR, _SDK_DIR))

        return msg

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "message",
            "time": self.time,
            "orderId": self.order_id,
            "severity": self.severity.name,
            "message": self.message,
            "tag": self.tag,
            "function": self.function,
            "fileName": self.file_name,
            "lineNumber": self.line_number,
        }
        if self.thread_name is not None or self.thread_id is not None:
            d["threadInfo"] = {
                "threadName": self.thread_name,
                "threadId": self.thread_id,
            }
        if self.stack_trace is not None:
            d["stackTrace"] = self.stack_trace
        if self.exception is not None:
            d["exception"] = self.exception
        return d
