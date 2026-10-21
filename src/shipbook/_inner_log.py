import logging
import sys
from typing import Optional

# The SDK's own diagnostics, off by default like the other SDKs' InnerLog. It never propagates:
# reaching the root logger would hand it to ShipbookHandler and ship the SDK's logs about shipping.
inner_log = logging.getLogger("shipbook.inner")
inner_log.propagate = False
inner_log.addHandler(logging.NullHandler())

_stderr_handler: Optional[logging.Handler] = None


def enable_inner_log(enable: bool) -> None:
    global _stderr_handler
    if enable and _stderr_handler is None:
        _stderr_handler = logging.StreamHandler(sys.stderr)
        _stderr_handler.setFormatter(logging.Formatter("Shipbook: %(message)s"))
        inner_log.addHandler(_stderr_handler)
        inner_log.setLevel(logging.DEBUG)
    elif not enable and _stderr_handler is not None:
        inner_log.removeHandler(_stderr_handler)
        _stderr_handler = None
