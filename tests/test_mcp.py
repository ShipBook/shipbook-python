import asyncio
import logging

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

from shipbook import context  # noqa: E402
from shipbook.handler import ShipbookHandler  # noqa: E402
from shipbook.integrations.mcp import ShipbookMiddleware  # noqa: E402


@pytest.fixture
def shipped_logger(active_runtime):
    log = logging.getLogger("mcp.tools")
    handler = ShipbookHandler()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    yield log
    log.removeHandler(handler)


def _server(log):
    server = MCPServer("test-server", middleware=[ShipbookMiddleware()])

    @server.tool()
    def get_logs(query: str) -> str:
        log.info("searching %s", query)
        return f"found {query}"

    @server.tool()
    def broken() -> str:
        raise RuntimeError("tool failed")

    return server


def _logs(active_runtime, connection):
    active_runtime.uploader.flush()
    return [log for s in connection.ingested_sessions() for log in s["logs"]]


async def _call(server, tool, arguments):
    async with Client(server) as client:
        return await client.call_tool(tool, arguments)


def test_a_tool_call_is_a_request_labeled_with_its_operation(
    active_runtime, connection, shipped_logger
):
    result = asyncio.run(_call(_server(shipped_logger), "get_logs", {"query": "errors"}))
    assert not result.is_error

    logs = _logs(active_runtime, connection)
    message = next(log for log in logs if log["type"] == "message")
    events = [
        log
        for log in logs
        if log["type"] == "requestEvent" and log["requestId"] == message["requestId"]
    ]
    assert message["message"] == "searching errors"
    assert [(e["event"], e["kind"], e["operation"]) for e in events] == [
        ("start", "rpc", "tools/call get_logs"),
        ("end", "rpc", "tools/call get_logs"),
    ]
    assert events[1]["outcome"] == "ok"
    assert context.get() is None


def test_a_failed_tool_is_a_failed_request(active_runtime, connection, shipped_logger):
    result = asyncio.run(_call(_server(shipped_logger), "broken", {}))
    assert result.is_error

    end = next(
        log
        for log in _logs(active_runtime, connection)
        if log["type"] == "requestEvent"
        and log["event"] == "end"
        and log["operation"] == "tools/call broken"
    )
    assert end["outcome"] == "error"


def test_calls_through_one_middleware_share_one_session(active_runtime, connection, shipped_logger):
    server = _server(shipped_logger)

    async def two_calls():
        async with Client(server) as client:
            await client.call_tool("get_logs", {"query": "a"})
            await client.call_tool("get_logs", {"query": "b"})

    asyncio.run(two_calls())
    messages = [log for log in _logs(active_runtime, connection) if log["type"] == "message"]
    sessions = {s["sessionId"] for s in connection.ingested_sessions() if s["logs"]}
    assert len(messages) == 2
    assert messages[0]["requestId"] != messages[1]["requestId"]
    assert len(sessions) == 1
