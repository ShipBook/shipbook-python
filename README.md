# Shipbook Python SDK

Ship your Python server logs to [Shipbook](https://shipbook.io) — with **zero new logging API to learn.** The SDK plugs into Python's standard `logging` module, so the code you already write just works:

```python
import logging
import shipbook

shipbook.start(app_id="YOUR_APP_ID", app_key="YOUR_APP_KEY")

log = logging.getLogger(__name__)
log.info("user signed in")
log.error("payment failed", exc_info=True)
```

Every `logging` call in your process is captured, batched, and uploaded to Shipbook in the background. Source location (file, function, line), the logger name (as the tag), thread info, and exception tracebacks all come across automatically — because Python's `logging` already records them.

## Install

```bash
pip install shipbook
```

Zero required dependencies. Optional framework helpers:

```bash
pip install "shipbook[fastapi]"   # or [flask], [django]
```

## How it works

`shipbook.start()` logs in to the Shipbook server, then attaches a single `ShipbookHandler` to the root logger. There is **no** separate Shipbook logging API — `ShipbookHandler` *is* the SDK. A background daemon thread batches records and posts them to Shipbook; nothing on your request path blocks on the network.

What ships is controlled by two independent gates:

1. **Standard `logging` levels** — records are only created if the logger's level allows them. To ship `DEBUG`/`INFO`, make sure the level permits it (or pass `capture_level=logging.DEBUG` to `start()`).
2. **Server-side config** — Shipbook's dashboard controls which tags/severities are actually uploaded, and can be changed without a redeploy.

## Attaching to a specific logger

By default the handler is attached to the root logger. To scope it yourself:

```python
shipbook.start(app_id="...", app_key="...", attach_to_root=False)
logging.getLogger("myapp").addHandler(shipbook.get_handler())
```

## Web frameworks — per-request user, IP & tracing

A `LogRecord` doesn't know which request it belongs to. The framework integrations bind each request to a Shipbook **session**, so logs carry the user, client IP, and trace id, and are grouped per request.

**FastAPI / Starlette**

```python
from shipbook.integrations.fastapi import ShipbookMiddleware
app.add_middleware(ShipbookMiddleware)
```

**Flask**

```python
from shipbook.integrations.flask import init_app
init_app(app)
```

**Django** — add to `MIDDLEWARE`:

```python
"shipbook.integrations.django.ShipbookMiddleware"
```

Attach the authenticated user by passing a `user_extractor` (FastAPI/Flask) or subclassing and overriding `get_user` (Django), or call `shipbook.register_user(...)` anywhere inside the request.

## Background jobs

Wrap background work so its logs are grouped as a named session:

```python
with shipbook.run_in_context(job_name="nightly-billing"):
    logging.getLogger(__name__).info("charging customers")
```

Anything logged outside a request or job falls back to a per-process background session — nothing is lost.

## Threads and executors

`contextvars` follow `await` and `asyncio` tasks automatically, but a manually
spawned thread or executor starts with a fresh context and would lose the
request's user/IP. Wrap the callable to carry the current context along:

```python
pool.submit(shipbook.preserve_context(do_work))
```

## Shutdown

Buffered logs are flushed on interpreter exit and on `SIGTERM`/`SIGINT`. To flush or stop explicitly:

```python
shipbook.flush()
shipbook.shutdown()
```

## License

MIT
