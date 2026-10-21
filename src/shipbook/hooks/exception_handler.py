import sys
import threading
from typing import Any, Callable, Optional

from ..models.exception import ExceptionLog

# on_exception(exception, fatal): fatal is the main thread's, which ends the process.
ExceptionCallback = Callable[[ExceptionLog, bool], None]

_prev_excepthook: Any = None
_prev_threading_hook: Any = None
_on_exception: Optional[ExceptionCallback] = None


def install(on_exception: ExceptionCallback) -> None:
    """Capture uncaught exceptions, then hand them to the previous hooks, which print them
    (the interpreter then exits for the main thread's). Exceptions in asyncio tasks reach
    ``logging`` (the ``asyncio`` logger) and are shipped as error messages."""
    global _prev_excepthook, _prev_threading_hook, _on_exception
    if _on_exception is not None:
        return
    _on_exception = on_exception
    _prev_excepthook = sys.excepthook
    _prev_threading_hook = threading.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        if _on_exception is not None and not issubclass(exc_type, KeyboardInterrupt):
            _on_exception(ExceptionLog.from_exc_info(exc_type, exc_value, exc_tb), True)
        _prev_excepthook(exc_type, exc_value, exc_tb)

    def _thread_excepthook(args):
        if _on_exception is not None and not issubclass(args.exc_type, KeyboardInterrupt):
            _on_exception(
                ExceptionLog.from_exc_info(args.exc_type, args.exc_value, args.exc_traceback), False
            )
        _prev_threading_hook(args)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def uninstall() -> None:
    global _on_exception
    if _on_exception is None:
        return
    sys.excepthook = _prev_excepthook
    threading.excepthook = _prev_threading_hook
    _on_exception = None
