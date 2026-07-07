from typing import Optional

# The active runtime, set by shipbook.start(). The handler reads it lazily so a
# ShipbookHandler attached before start() (or after shutdown()) is simply inert.
_active: Optional[object] = None


def get_active():
    return _active


def set_active(runtime) -> None:
    global _active
    _active = runtime
