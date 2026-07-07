"""Minimal usage: attach Shipbook to stdlib logging and log.

Run:  SHIPBOOK_APP_ID=... SHIPBOOK_APP_KEY=... python examples/plain_script.py
"""

import logging
import os

import shipbook

shipbook.start(
    app_id=os.environ["SHIPBOOK_APP_ID"],
    app_key=os.environ["SHIPBOOK_APP_KEY"],
    capture_level=logging.DEBUG,  # ensure DEBUG/INFO records are created
)

log = logging.getLogger("example.plain")

log.info("service started")
log.debug("loaded config: %s", {"workers": 4})
log.warning("cache miss for key %s", "user:42")

try:
    ratio = 100 / 0
except ZeroDivisionError:
    log.exception("failed to compute ratio")

# Flush before the short script exits (the exit hook also does this).
shipbook.flush()
shipbook.shutdown()
