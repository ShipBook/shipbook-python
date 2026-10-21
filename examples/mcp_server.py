"""An MCP server whose tool calls are read in Shipbook request by request.

Run:  SHIPBOOK_APP_ID=... SHIPBOOK_APP_KEY=... python examples/mcp_server.py
"""

import logging
import os

from mcp.server.mcpserver import MCPServer

import shipbook
from shipbook.integrations.mcp import ShipbookMiddleware

shipbook.start(
    app_id=os.environ["SHIPBOOK_APP_ID"],
    app_key=os.environ["SHIPBOOK_APP_KEY"],
    capture_level=logging.INFO,
)

server = MCPServer("orders", middleware=[ShipbookMiddleware()])
log = logging.getLogger("example.mcp")


@server.tool()
def find_order(order_id: str) -> str:
    log.info("looking up order %s", order_id)
    return f"order {order_id}: shipped"


if __name__ == "__main__":
    server.run()  # stdio
