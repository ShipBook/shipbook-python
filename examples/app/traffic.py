"""Calls the Orders API the way its clients would, so there is something to read in Shipbook.

Run it while the API is up:  python traffic.py
"""

import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional

BASE_URL = os.environ.get("ORDERS_API", "http://localhost:3001")
SAM = {"Authorization": "Bearer token-sam", "Cookie": f"login={uuid.uuid4()}"}
ADDRESS = {"name": "Sam Taylor", "street": "12 Harbor St", "city": "Haifa"}
ITEMS = [{"name": "Compass", "price": 24.5}, {"name": "Rope", "price": 9.0}]


def call(
    method: str, path: str, body: Optional[Any] = None, headers: Optional[dict[str, str]] = None
) -> Any:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "orders-traffic/1.0",
            "x-request-id": str(uuid.uuid4()),
            **(headers or {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            status, text = response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode()
    print(f"{status} {method} {path}")
    return json.loads(text) if text.startswith(("{", "[")) else text


def main() -> None:
    call("GET", "/api/health")

    # A visitor who signs in: the handler attaches the user with register_user().
    call("POST", "/api/login", {"user_id": "u-2002", "email": "dana@example.com"})

    # Sam's requests share a login cookie, so they are one session in Shipbook.
    order = {"items": ITEMS, "address": {**ADDRESS, "zip": "3303"}}
    with_zip = call("POST", "/api/orders", order, SAM)
    call("GET", f"/api/orders/{with_zip['orderId']}", headers=SAM)
    call("GET", "/api/orders", headers={**SAM, "x-tenant": "acme"})

    # No zip code: the order is saved with a warning and without a shipping estimate.
    without_zip = call("POST", "/api/orders", {"items": ITEMS, "address": ADDRESS}, SAM)

    # A 404 is the client's mistake; a 500 is a failed request.
    call("GET", "/api/orders/9999", headers=SAM)
    call("POST", f"/api/orders/{without_zip['orderId']}/refund", headers=SAM)

    # JSON-RPC: the request is labeled "tools/call get-order".
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get-order"}}
    call("POST", "/rpc", rpc)


if __name__ == "__main__":
    main()
