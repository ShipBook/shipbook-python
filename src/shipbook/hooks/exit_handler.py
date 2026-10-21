import atexit
import signal
from typing import Callable, Optional

_EXIT_SIGNALS = (signal.SIGTERM, signal.SIGINT)

_on_exit: Optional[Callable[[], object]] = None
_prev_handlers: dict = {}


def install(on_exit: Callable[[], object]) -> None:
    """Run ``on_exit`` (a bounded send of the queue) before the process ends: at interpreter
    exit, and on SIGTERM/SIGINT, which by default end the process without running atexit.
    The previous signal handler still runs after it, so an app's own handler keeps working,
    and a default SIGTERM still terminates the process."""
    global _on_exit
    if _on_exit is not None:
        return
    _on_exit = on_exit
    atexit.register(_run)
    for sig in _EXIT_SIGNALS:
        try:
            _prev_handlers[sig] = signal.signal(sig, _signal_handler)
        except ValueError:
            pass  # not the main thread: only atexit applies


def uninstall() -> None:
    global _on_exit
    if _on_exit is None:
        return
    atexit.unregister(_run)
    for sig, prev in _prev_handlers.items():
        if signal.getsignal(sig) is _signal_handler:
            signal.signal(sig, prev)
    _prev_handlers.clear()
    _on_exit = None


def _run() -> None:
    if _on_exit is not None:
        _on_exit()


def _signal_handler(signum, frame) -> None:
    _run()
    prev = _prev_handlers.get(signum)
    if callable(prev):
        prev(signum, frame)
    elif prev == signal.SIG_DFL:
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)
