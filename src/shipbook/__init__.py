"""Shipbook logging SDK for Python servers.

Attach Shipbook to the standard library ``logging`` and your logs ship to the
cloud — there is no separate Shipbook logging API::

    import logging
    import shipbook

    shipbook.start(app_id="...", app_key="...")
    logging.getLogger(__name__).info("hello from Python")
"""

from .context import preserve_context, register_user
from .context import run_job as run_in_context
from .generated.version import SDK_VERSION, __version__
from .handler import ShipbookHandler
from .models.request_context import RequestContext
from .models.user import User
from .severity import Severity
from .shipbook import (
    flush,
    get_handler,
    set_connection_url,
    shutdown,
    start,
)

__all__ = [
    "start",
    "shutdown",
    "flush",
    "get_handler",
    "set_connection_url",
    "register_user",
    "run_in_context",
    "preserve_context",
    "ShipbookHandler",
    "Severity",
    "User",
    "RequestContext",
    "SDK_VERSION",
    "__version__",
]
