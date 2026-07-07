import itertools
from datetime import datetime, timezone

_order_counter = itertools.count(1)


def next_order_id() -> int:
    """Process-global monotonic ordering id for logs. ``itertools.count`` is
    thread-safe for a single ``next()`` call under CPython."""
    return next(_order_counter)


def iso_now() -> str:
    return to_iso(datetime.now(timezone.utc))


def to_iso(dt: datetime) -> str:
    """ISO 8601 with millisecond precision and a ``Z`` suffix, matching
    JavaScript's ``Date.toISOString()`` (the format the server parses)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
