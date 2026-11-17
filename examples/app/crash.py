"""A crash: the uncaught exception is sent to Shipbook before Python prints it and exits.

Loglytics groups it by the innermost frame of this file, not by the standard library's.

Run:  python crash.py
"""

import json
import logging

from common import start_shipbook

start_shipbook()

log = logging.getLogger("orders.importer")


def parse_price_list(raw: str) -> dict:
    return json.loads(raw)


def import_prices() -> None:
    log.info("Importing the supplier's price list")
    # The file is cut off in the middle, and nothing catches the parse error.
    parse_price_list('{"compass": 24.5, "rope": ')


if __name__ == "__main__":
    import_prices()
