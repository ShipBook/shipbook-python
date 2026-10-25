from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .user import User


# eq=False keeps identity hashing: a context keys its request's flushQueue (a WeakKeyDictionary).
@dataclass(eq=False)
class RequestContext:
    """Ambient per-task context that gives a log its session identity.

    A ``LogRecord`` knows only its call site; the request/user/IP/background
    facts come from whichever ``RequestContext`` is active on the current
    ``contextvars`` context when the log is emitted.
    """

    session_id: str
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: Optional[str] = None
    # Minted per request; groups the request's logs and its start/end events.
    request_id: Optional[str] = None
    # The raw x-shipbook-session header of a linked caller; parsed by the server.
    caller_session_link: Optional[str] = None
    user: Optional[User] = None
    # Session-level, constant for its life (a job's options, an MCP transport);
    # a request's facts go on its start event.
    metadata: Optional[dict[str, Any]] = None
    is_background: bool = False
    job_name: Optional[str] = None
