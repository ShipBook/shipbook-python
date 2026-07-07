import logging

from . import _state
from .models.message import Message
from .severity import Severity


class ShipbookHandler(logging.Handler):
    """The one public logging surface. Attach it to any logger (``start()``
    attaches it to the root logger for you) and standard ``logging`` calls flow
    to Shipbook.

    It never blocks on the network: ``emit`` maps the record to a Shipbook
    message and enqueues it; a background thread does the upload.
    """

    def emit(self, record: logging.LogRecord) -> None:
        runtime = _state.get_active()
        if runtime is None:
            return
        try:
            config = runtime.config
            severity = Severity.from_logging_level(record.levelno)
            tag = record.name
            if not config.should_ship(tag, severity):
                return

            css = config.call_stack_severity(tag)
            include_stack = css != Severity.Off and severity.value <= css.value

            message = Message.from_record(record, severity, include_stack)
            runtime.uploader.push(message)
        except Exception:  # noqa: BLE001 — logging handlers must never raise into user code
            self.handleError(record)
