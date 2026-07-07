import logging

from shipbook.handler import ShipbookHandler
from shipbook.severity import Severity


def _attach(logger):
    handler = ShipbookHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return handler


def test_stdlib_logging_produces_ingest_payload(active_runtime, connection):
    log = logging.getLogger("e2e.test")
    handler = _attach(log)
    try:
        log.info("hello from stdlib")
    finally:
        log.removeHandler(handler)

    active_runtime.uploader._send()
    sessions = connection.ingested_sessions()
    assert len(sessions) == 1
    logs = sessions[0]["logs"]
    assert logs[0]["message"] == "hello from stdlib"
    assert logs[0]["tag"] == "e2e.test"
    assert logs[0]["severity"] == "Info"
    # location came straight off the LogRecord
    assert logs[0]["fileName"].endswith("test_handler_e2e.py")
    assert logs[0]["lineNumber"] > 0


def test_exception_logging_ships_exception(active_runtime, connection):
    log = logging.getLogger("e2e.exc")
    handler = _attach(log)
    try:
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            log.exception("handling failed")
    finally:
        log.removeHandler(handler)

    active_runtime.uploader._send()
    entry = connection.ingested_sessions()[0]["logs"][0]
    assert entry["severity"] == "Error"
    assert entry["exception"]["name"] == "RuntimeError"
    assert entry["exception"]["reason"] == "kaboom"


def test_config_gate_drops_below_threshold(active_runtime, connection):
    from shipbook.config import Config

    # Only Warning-or-worse ships.
    active_runtime.config = Config.from_dict(
        {
            "appenders": [{"type": "SBCloudAppender", "name": "cloud", "config": {}}],
            "loggers": [{"name": "", "severity": "Warning", "appenderRef": "cloud"}],
        }
    )
    log = logging.getLogger("e2e.gate")
    handler = _attach(log)
    try:
        log.info("dropped")
        log.error("kept")
    finally:
        log.removeHandler(handler)

    active_runtime.uploader._send()
    messages = [entry["message"] for s in connection.ingested_sessions() for entry in s["logs"]]
    assert "kept" in messages
    assert "dropped" not in messages


def test_handler_inert_before_start():
    # No active runtime — emit must be a silent no-op, not raise.
    from shipbook import _state

    assert _state.get_active() is None
    log = logging.getLogger("e2e.inert")
    handler = _attach(log)
    try:
        log.info("nowhere to go")
    finally:
        log.removeHandler(handler)


def test_severity_value_ordering():
    assert Severity.Error.value < Severity.Warning.value < Severity.Info.value
