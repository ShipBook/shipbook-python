from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .attributes import Attributes
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
    # The app's own facts about a job's session; a request's go on its start event.
    attributes: Optional[Attributes] = None
    is_background: bool = False
    job_name: Optional[str] = None
