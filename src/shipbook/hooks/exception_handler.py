import logging
import sys
import threading

_logger = logging.getLogger("shipbook.uncaught")

_prev_excepthook = None
_prev_threading_hook = None
_installed = False


def install() -> None:
    """Route uncaught exceptions through ``logging`` (so they reach the
    Shipbook handler) while preserving the previous hooks."""
    global _prev_excepthook, _prev_threading_hook, _installed
    if _installed:
        return
    _installed = True

    _prev_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            _logger.error(
                "Uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
            )
        if _prev_excepthook is not None:
            _prev_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    # threading.excepthook exists on Python 3.8+
    _prev_threading_hook = threading.excepthook

    def _thread_excepthook(args):
        if not issubclass(args.exc_type, KeyboardInterrupt):
            _logger.error(
                "Uncaught exception in thread %s",
                args.thread.name if args.thread else "?",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        if _prev_threading_hook is not None:
            _prev_threading_hook(args)

    threading.excepthook = _thread_excepthook


def uninstall() -> None:
    global _installed
    if not _installed:
        return
    if _prev_excepthook is not None:
        sys.excepthook = _prev_excepthook
    if _prev_threading_hook is not None:
        threading.excepthook = _prev_threading_hook
    _installed = False
