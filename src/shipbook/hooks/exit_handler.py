import atexit
import signal
from typing import Callable, Optional

_registered: Optional[Callable[[], None]] = None
_prev_handlers: dict = {}


def install(on_exit: Callable[[], None]) -> None:
    """Flush on interpreter exit and on SIGTERM/SIGINT (so buffered logs aren't
    lost when a container is stopped). Chains any pre-existing signal handler."""
    global _registered
    _registered = on_exit
    atexit.register(_run)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            _prev_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError):
            # Not on the main thread, or signal unavailable on this platform.
            pass


def _run() -> None:
    if _registered is not None:
        _registered()


def _signal_handler(signum, frame) -> None:
    _run()
    prev = _prev_handlers.get(signum)
    if callable(prev):
        prev(signum, frame)
    elif prev == signal.SIG_DFL:
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)
