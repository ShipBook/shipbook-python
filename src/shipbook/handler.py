import contextlib
import copy
import logging
from typing import Optional

from . import _state
from . import context as _context
from .models.message import Message, current_stack
from .severity import Severity


class ShipbookHandler(logging.Handler):
    """The one public logging surface. Attach it to any logger (``start()``
    attaches it to the root logger for you) and standard ``logging`` calls flow
    to Shipbook.

    It never blocks on the network: ``emit`` maps the record to a Shipbook
    message and enqueues it; a background thread does the upload.
    """

    def emit(self, record: logging.LogRecord) -> None:
        self._keep_default_output(record)
        runtime = _state.get_active()
        if runtime is None:
            return
        try:
            if runtime.config is None:
                record = self._held_copy(record)
            # Django logs a 4xx after its middleware has returned, with the request on the record.
            request = None if _context.get() else getattr(record, "request", None)
            late = getattr(request, "shipbook_context", None)
            with _context.run(late) if late else contextlib.nullcontext():
                runtime.when_configured(lambda: self._ship(runtime, record))
        except Exception:  # noqa: BLE001 — logging handlers must never raise into user code
            self.handleError(record)

    def _keep_default_output(self, record: logging.LogRecord) -> None:
        """Python prints warnings and errors itself only while no handler is attached. Being the
        only handler must not silence an app that never configured logging, so it still prints."""
        last_resort = logging.lastResort
        if last_resort is None or record.levelno < last_resort.level:
            return
        logger: Optional[logging.Logger] = logging.getLogger(record.name)
        attached = False
        while logger is not None:
            if any(handler is not self for handler in logger.handlers):
                return
            attached = attached or self in logger.handlers
            if not logger.propagate:
                break
            logger = logger.parent
        if attached:
            last_resort.handle(record)

    def _ship(self, runtime, record: logging.LogRecord) -> None:
        try:
            config = runtime.config
            severity = Severity.from_logging_level(record.levelno)
            tag = record.name
            if not config.should_ship(tag, severity):
                return

            css = config.call_stack_severity(tag)
            include_stack = css != Severity.Off and severity.value <= css.value
            runtime.uploader.push(Message.from_record(record, severity, include_stack))
        except Exception:  # noqa: BLE001 — logging handlers must never raise into user code
            self.handleError(record)

    @staticmethod
    def _held_copy(record: logging.LogRecord) -> logging.LogRecord:
        # Shipped later, so what can change is fixed now: the formatted message and the call stack.
        held = copy.copy(record)
        held.msg = record.getMessage()
        held.args = None
        held.shipbook_stack = current_stack()  # type: ignore[attr-defined]
        return held
