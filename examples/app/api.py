"""Orders API: a FastAPI service read in Shipbook request by request.

Every request is recorded with its method, route, status and duration, and its logs are
grouped under it with the signed-in user. It is also the backend of the session-linking
demo in shipbook-js (examples/README.md there): the browser shop posts to /api/orders.

Run:  uvicorn api:app --port 3001      then, in another terminal:  python traffic.py
"""

import itertools
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from common import start_shipbook
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import shipbook
from shipbook.integrations.fastapi import ShipbookMiddleware

start_shipbook()

log = logging.getLogger("orders.api")
mail_log = logging.getLogger("orders.mail")

app = FastAPI(title="Orders API")
mailer = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mailer")

# Stands in for your auth: a bearer token names the signed-in user.
ACCOUNTS = {
    "token-sam": shipbook.User(
        user_id="u-1001",
        user_name="sam.taylor",
        full_name="Sam Taylor",
        email="sam.taylor@example.com",
    ),
}


def signed_in_user(request: Request) -> Optional[shipbook.User]:
    return ACCOUNTS.get(request.headers.get("authorization", "").removeprefix("Bearer "))


app.add_middleware(
    ShipbookMiddleware,
    user_extractor=signed_in_user,
    # Requests that carry the same login cookie are read as one session.
    session_extractor=lambda request: request.cookies.get("login"),
    attributes_extractor=lambda request: {"tenant": request.headers.get("x-tenant", "public")},
)
# Added last, so it runs first: the browser's preflight is answered before Shipbook sees it.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Item(BaseModel):
    name: str
    price: float


class Address(BaseModel):
    name: str
    street: str
    city: str
    zip: Optional[str] = None


class NewOrder(BaseModel):
    items: list[Item]
    address: Address


class Login(BaseModel):
    user_id: str
    email: str


orders: dict[int, dict[str, Any]] = {}
order_ids = itertools.count(1042)


def estimate_shipping(address: Address) -> dict[str, str]:
    time.sleep(0.12)
    if not address.zip:
        raise ValueError("shipping service: zip code is required")
    return {"eta": "Friday"}


def send_confirmation(order_id: int) -> None:
    time.sleep(0.05)
    mail_log.info("Confirmation mail sent for order %s", order_id)


@app.get("/api/health")
async def health():
    log.debug("Health check")
    return {"status": "ok"}


@app.post("/api/login")
async def login(body: Login):
    # The user is only known here, inside the request, so it is attached from the handler.
    shipbook.register_user(body.user_id, email=body.email)
    log.info("%s signed in", body.user_id)
    return {"ok": True}


@app.get("/api/orders")
async def list_orders():
    log.info("Listing %d orders", len(orders))
    return list(orders.values())


@app.get("/api/orders/{order_id}")
async def get_order(order_id: int):
    order = orders.get(order_id)
    if order is None:
        log.warning("Order %s not found", order_id)
        raise HTTPException(status_code=404, detail="No such order")
    log.debug("Order %s loaded", order_id)
    return order


@app.post("/api/orders")
def create_order(order: NewOrder):
    order_id = next(order_ids)
    total = sum(item.price for item in order.items)
    log.info("Order %s received: %d items, $%.2f", order_id, len(order.items), total)
    log.info("Payment authorized for order %s", order_id)

    shipping = None
    try:
        shipping = estimate_shipping(order.address)
    except ValueError as error:
        # Shipping is "optional", so a failed estimate doesn't fail the order.
        log.warning("No shipping estimate for order %s: %s", order_id, error)

    orders[order_id] = {"orderId": order_id, "total": total, "installments": 0}
    log.info("Order %s saved", order_id)
    # The mail goes out on another thread; preserve_context keeps its logs in this request.
    mailer.submit(shipbook.preserve_context(send_confirmation), order_id)
    return {"orderId": order_id, "shipping": shipping}


@app.post("/api/orders/{order_id}/refund")
def refund_order(order_id: int):
    order = orders[order_id]
    log.info("Refunding order %s", order_id)
    # The bug: an order paid at once has no installments. The request fails with a 500.
    per_installment = order["total"] / order["installments"]
    return {"refunded": per_installment * order["installments"]}


@app.post("/rpc")
async def rpc(call: dict[str, Any]):
    # A JSON-RPC endpoint (as an MCP server over HTTP is): Shipbook labels the request
    # with what it was asked to do, e.g. "tools/call get-order".
    log.info("RPC %s", call.get("method"))
    return {"jsonrpc": "2.0", "id": call.get("id"), "result": {"ok": True}}
