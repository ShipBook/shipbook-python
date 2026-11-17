"""Background work without a web framework: jobs, queue messages, threads and asyncio.

Each job run is its own session in Shipbook and counts as one request, so the console
shows when it started, how long it took and whether it raised.

Run:  python jobs.py
"""

import asyncio
import logging
import threading
import time

from common import start_shipbook

import shipbook

start_shipbook()

log = logging.getLogger("orders.worker")
billing_log = logging.getLogger("orders.billing")
queue_log = logging.getLogger("orders.queue")


def nightly_billing() -> None:
    with shipbook.run_in_context("nightly-billing", attributes={"region": "eu", "batch": 128}):
        billing_log.info("Starting the billing run")
        time.sleep(0.1)
        billing_log.info("Charged %d customers", 128)
        billing_log.warning("1 payment method expired")


def inventory_sync() -> None:
    # A job that raises ends as a failed request.
    with shipbook.run_in_context("inventory-sync"):
        billing_log.info("Syncing inventory with the warehouse")
        raise ConnectionError("warehouse API timed out")


def process_queue() -> None:
    # A queue message isn't an HTTP request, but it is read like one.
    for message in ("order 1042", "order 1043"):
        with shipbook.run_in_request(shipbook.RequestKind.Rpc, f"process {message}"):
            queue_log.info("Processing %s", message)
            time.sleep(0.05)
            queue_log.debug("Done with %s", message)


def restock() -> None:
    raise ValueError("restock failed: unknown item")


async def refresh_prices() -> None:
    raise TimeoutError("price feed did not answer")


async def run_asyncio_task() -> None:
    task = asyncio.ensure_future(refresh_prices())
    await asyncio.sleep(0.05)
    # Dropped without being awaited: asyncio reports the exception through logging.
    del task


def main() -> None:
    # Outside any request or job: these land in the process's background session.
    log.info("Worker started")
    log.debug("Configuration loaded")

    nightly_billing()
    try:
        inventory_sync()
    except ConnectionError:
        log.exception("inventory-sync failed")
    process_queue()

    # An exception that ends a thread is captured too; the process keeps running.
    thread = threading.Thread(target=restock, name="restock")
    thread.start()
    thread.join()

    asyncio.run(run_asyncio_task())

    log.info("Worker finished")
    # Queued logs are also sent when the process exits; flush() sends them now.
    shipbook.flush()


if __name__ == "__main__":
    main()
