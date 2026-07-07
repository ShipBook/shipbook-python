from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .user import User


@dataclass
class RequestContext:
    """Ambient per-task context that gives a log its session identity.

    A ``LogRecord`` knows only its call site; the request/user/IP/background
    facts come from whichever ``RequestContext`` is active on the current
    ``contextvars`` context when the log is emitted.
    """

    session_id: str
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: Optional[str] = None
    user: Optional[User] = None
    metadata: Optional[dict[str, Any]] = None
    is_background: bool = False
    job_name: Optional[str] = None
