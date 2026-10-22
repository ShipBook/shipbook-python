from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from .._util import next_order_id, to_iso


class RequestEventPhase(str, Enum):
    Start = "start"
    End = "end"


# The protocol a request came in on; each kind fills its own fields (http: method/route/status).
class RequestKind(str, Enum):
    Http = "http"
    Rpc = "rpc"
    Job = "job"


# Whether a request failed, the same for every kind; each kind maps its own result onto it.
class RequestOutcome(str, Enum):
    Ok = "ok"
    Error = "error"


# Two write-once events per backend request; the end repeats everything the start had.
@dataclass
class RequestEvent:
    event: RequestEventPhase
    kind: RequestKind
    method: Optional[str] = None
    route: Optional[str] = None
    # What a multiplexed endpoint was asked to do, e.g. an MCP "tools/call get-logs".
    operation: Optional[str] = None
    start_time: Optional[datetime] = None
    start_order_id: Optional[int] = None
    status: Optional[int] = None
    outcome: Optional[RequestOutcome] = None
    duration: Optional[int] = None  # ms
    error_code: Optional[int] = None  # rpc: the JSON-RPC error code
    order_id: int = field(default_factory=next_order_id)
    time: str = field(default_factory=lambda: to_iso(datetime.now(timezone.utc)))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "requestEvent",
            "time": self.time,
            "orderId": self.order_id,
            "event": self.event.value,
            "kind": self.kind.value,
        }
        optional = {
            "method": self.method,
            "route": self.route,
            "operation": self.operation,
            "startTime": to_iso(self.start_time) if self.start_time else None,
            "startOrderId": self.start_order_id,
            "status": self.status,
            "outcome": self.outcome.value if self.outcome else None,
            "duration": self.duration,
            "errorCode": self.error_code,
        }
        d.update({key: value for key, value in optional.items() if value is not None})
        return d
