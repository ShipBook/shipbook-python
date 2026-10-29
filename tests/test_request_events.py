import pytest

import shipbook
from shipbook import context
from shipbook.models.message import Message
from shipbook.request_events import json_rpc_operation, open_request
from shipbook.severity import Severity


@pytest.mark.parametrize(
    ("body", "operation"),
    [
        (
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get-logs"}},
            "tools/call get-logs",
        ),
        (
            {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": "log://1"}},
            "resources/read log://1",
        ),
        (
            [
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "method": "ping"},
            ],
            "tools/list, ping",
        ),
        ({"method": "not json-rpc"}, None),
        ({"jsonrpc": "2.0", "result": {}}, None),
        ("plain text", None),
        (None, None),
    ],
)
def test_json_rpc_operation(body, operation):
    assert json_rpc_operation(body) == operation


def _events(connection):
    return [
        log for s in connection.ingested_sessions() for log in s["logs"] if log["type"] != "message"
    ]


def _log(runtime):
    # Request events go up only around a saved log.
    runtime.uploader.push(Message(severity=Severity.Info, message="working", tag="job"))


def test_run_in_request_is_one_request_of_the_background_session(active_runtime, connection):
    with shipbook.run_in_request(shipbook.RequestKind.Rpc, "process order") as ctx:
        assert context.get() is ctx
        _log(active_runtime)
    assert context.get() is None
    active_runtime.uploader.flush()

    start, end = _events(connection)
    assert ctx.session_id == active_runtime.uploader.background_context.session_id
    assert (start["event"], start["kind"], start["operation"]) == ("start", "rpc", "process order")
    assert (end["event"], end["outcome"], end["startOrderId"]) == ("end", "ok", start["orderId"])
    assert start["requestId"] == end["requestId"] == ctx.request_id
    assert connection.ingested_sessions()[0]["requests"] == 1


def test_run_in_request_ends_with_an_error_and_reraises(active_runtime, connection):
    with pytest.raises(ValueError):
        with shipbook.run_in_request(shipbook.RequestKind.Rpc, "process order"):
            raise ValueError("bad order")
    active_runtime.uploader.flush()
    assert _events(connection)[-1]["outcome"] == "error"


def test_run_in_request_joins_the_current_session(active_runtime, connection):
    with shipbook.run_in_context("nightly"):
        job = context.get()
        with shipbook.run_in_request(shipbook.RequestKind.Rpc, "step") as ctx:
            assert ctx.session_id == job.session_id
            assert ctx.request_id and ctx.request_id != job.request_id


def test_run_in_context_runs_the_job_as_a_request(active_runtime, connection):
    with shipbook.run_in_context("nightly", attributes={"k": "v"}) as ctx:
        assert context.get() is ctx
        _log(active_runtime)
    active_runtime.uploader.flush()

    [session] = connection.ingested_sessions()
    assert (session["jobName"], session["isBackground"], session["attributes"]) == (
        "nightly",
        True,
        {"k": "v"},
    )
    assert session["requests"] == 1
    start, end = _events(connection)
    assert (start["kind"], start["operation"], end["outcome"]) == ("job", "nightly", "ok")
    assert start["requestId"] == end["requestId"] == ctx.request_id


def test_run_in_context_ends_as_an_error_and_reraises(active_runtime, connection):
    with pytest.raises(ValueError):
        with shipbook.run_in_context("nightly"):
            raise ValueError("boom")
    active_runtime.uploader.flush()
    assert _events(connection)[-1]["outcome"] == "error"


def test_each_job_run_is_its_own_session(active_runtime, connection):
    with shipbook.run_in_context("nightly") as first:
        pass
    with shipbook.run_in_context("nightly") as second:
        pass
    assert first.session_id != second.session_id


def test_open_request_records_an_rpc_error_code(active_runtime, connection):
    session = active_runtime.uploader.background_context
    _, end = open_request(session, shipbook.RequestKind.Rpc, "tools/call get-logs")
    end(shipbook.RequestOutcome.Error, -32602)
    active_runtime.uploader.flush()
    assert _events(connection)[-1]["errorCode"] == -32602
