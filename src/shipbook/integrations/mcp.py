import uuid
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS, CallToolResult
from pydantic import ValidationError

from .. import context as _context
from ..models.request_context import RequestContext
from ..models.request_event import RequestKind, RequestOutcome
from ..request_events import json_rpc_operation, open_request


class ShipbookMiddleware:
    """MCP server middleware (``mcp`` 2.x): each call to the server is a Shipbook request,
    labeled with its operation (e.g. ``tools/call get-logs``), and the tool's logs are
    grouped under it. Works over any transport::

        server = MCPServer("my-server", middleware=[ShipbookMiddleware()])

    All requests through one middleware share one session: a stdio server serves one client.
    Over HTTP, the ASGI middleware already records each request with its operation, so
    this one only steps aside.
    """

    def __init__(self) -> None:
        self._session = RequestContext(
            session_id=str(uuid.uuid4()), is_background=False, metadata={"transport": "mcp"}
        )

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        current = _context.get()
        # A notification isn't a request.
        if ctx.request_id is None or (current is not None and current.request_id):
            return await call_next(ctx)

        call = {"jsonrpc": "2.0", "method": ctx.method, "params": ctx.params}
        request_ctx, end = open_request(self._session, RequestKind.Rpc, json_rpc_operation(call))
        token = _context.set_context(request_ctx)
        try:
            result = await call_next(ctx)
        except MCPError as error:
            end(RequestOutcome.Error, error.error.code)
            raise
        except ValidationError:
            end(RequestOutcome.Error, INVALID_PARAMS)
            raise
        except BaseException:
            end(RequestOutcome.Error, None)
            raise
        finally:
            _context.reset(token)

        # A tool that failed answers with isError rather than a JSON-RPC error; it still failed.
        failed = isinstance(result, CallToolResult) and result.is_error
        failed = failed or (isinstance(result, dict) and result.get("isError") is True)
        end(RequestOutcome.Error if failed else RequestOutcome.Ok, None)
        return result
