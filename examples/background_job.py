"""Group a background job's logs into a named Shipbook session."""

import logging
import os

import shipbook

shipbook.start(
    app_id=os.environ["SHIPBOOK_APP_ID"],
    app_key=os.environ["SHIPBOOK_APP_KEY"],
    capture_level=logging.INFO,
)

log = logging.getLogger("example.job")


def run_billing():
    with shipbook.run_in_context(job_name="nightly-billing", attributes={"tenant": "acme"}):
        log.info("starting billing run")
        log.info("charged %d customers", 128)
        log.warning("1 payment method expired")


if __name__ == "__main__":
    run_billing()
    shipbook.flush()
    shipbook.shutdown()
