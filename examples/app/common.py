"""Starts Shipbook for every script of the example app, from the credentials in ``.env``."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

import shipbook

APP_VERSION = "1.0.0"


def start_shipbook() -> None:
    load_dotenv(Path(__file__).with_name(".env"))

    # The SDK's own diagnostics (login, uploads), on stderr.
    shipbook.enable_inner_log(os.environ.get("SHIPBOOK_INNER_LOG") == "1")
    # Another Shipbook API, e.g. a staging environment.
    if os.environ.get("SHIPBOOK_URL"):
        shipbook.set_connection_url(os.environ["SHIPBOOK_URL"])

    shipbook.start(
        app_id=os.environ["SHIPBOOK_APP_ID"],
        app_key=os.environ["SHIPBOOK_APP_KEY"],
        app_version=APP_VERSION,
        # Python drops info and debug records unless the level allows them.
        capture_level=logging.DEBUG,
    )
