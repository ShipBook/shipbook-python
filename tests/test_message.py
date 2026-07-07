import logging

from shipbook.models.message import Message
from shipbook.severity import Severity


def _record(**kwargs) -> logging.LogRecord:
    defaults = dict(
        name="myapp.svc",
        level=logging.INFO,
        pathname="/srv/app/svc.py",
        lineno=42,
        msg="hello %s",
        args=("world",),
        exc_info=None,
        func="handle",
    )
    defaults.update(kwargs)
    return logging.LogRecord(
        name=defaults["name"],
        level=defaults["level"],
        pathname=defaults["pathname"],
        lineno=defaults["lineno"],
        msg=defaults["msg"],
        args=defaults["args"],
        exc_info=defaults["exc_info"],
        func=defaults["func"],
    )


def test_from_record_maps_fields():
    rec = _record()
    msg = Message.from_record(rec, Severity.Info, include_stack=False)
    d = msg.to_dict()
    assert d["type"] == "message"
    assert d["severity"] == "Info"
    assert d["message"] == "hello world"  # %-formatting applied
    assert d["tag"] == "myapp.svc"
    assert d["function"] == "handle"
    assert d["fileName"] == "/srv/app/svc.py"
    assert d["lineNumber"] == 42
    assert d["threadInfo"]["threadName"] is not None
    assert "orderId" in d and d["time"].endswith("Z")
    assert "exception" not in d
    assert "stackTrace" not in d


def test_order_id_increments():
    a = Message.from_record(_record(), Severity.Info, include_stack=False)
    b = Message.from_record(_record(), Severity.Info, include_stack=False)
    assert b.order_id > a.order_id


def test_exception_captured_from_exc_info():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = _record(level=logging.ERROR, exc_info=sys.exc_info())
    msg = Message.from_record(rec, Severity.Error, include_stack=False)
    d = msg.to_dict()
    assert d["exception"]["name"] == "ValueError"
    assert d["exception"]["reason"] == "boom"
    assert len(d["exception"]["stackTrace"]) >= 1
    frame = d["exception"]["stackTrace"][-1]
    assert frame["methodName"] and frame["fileName"] and frame["lineNumber"]
    # stackTrace mirrors the exception stack
    assert d["stackTrace"] == d["exception"]["stackTrace"]


def test_include_stack_trims_sdk_and_logging_frames():
    msg = Message.from_record(_record(), Severity.Verbose, include_stack=True)
    d = msg.to_dict()
    assert "stackTrace" in d
    for frame in d["stackTrace"]:
        assert "/shipbook/" not in frame["fileName"]
        assert "/logging/" not in frame["fileName"]
