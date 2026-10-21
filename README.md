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
pip install "shipbook[fastapi]"   # or [flask], [django], [mcp]
```

## How it works

`shipbook.start()` attaches a single `ShipbookHandler` to the root logger and returns at once; it logs in to Shipbook on a background thread, so an unreachable API never delays your app's startup. There is **no** separate Shipbook logging API — `ShipbookHandler` *is* the SDK. Logs are kept in memory and uploaded in batches by a background thread; nothing on your request path blocks on the network, and nothing is written to disk.

What ships is controlled by two independent gates:

1. **Standard `logging` levels** — records are only created if the logger's level allows them. To ship `DEBUG`/`INFO`, make sure the level permits it (or pass `capture_level=logging.DEBUG` to `start()`).
2. **Server-side config** — Shipbook's dashboard controls which tags/severities are actually uploaded, and can be changed without a redeploy. Until the first config arrives, logs are held and then filtered by it, so a filter set in the dashboard also applies to startup logs.

With the **Accumulate** config, logs below the warning level are held per request and uploaded only when that request logs a warning or error — as their context. Healthy requests cost nothing.

To point the SDK at another Shipbook API (for example a staging environment), call `shipbook.set_connection_url(url)` before `start()`.

## Attaching to a specific logger

By default the handler is attached to the root logger. To scope it yourself:

```python
shipbook.start(app_id="...", app_key="...", attach_to_root=False)
logging.getLogger("myapp").addHandler(shipbook.get_handler())
```

## Web frameworks — read your server request by request

A `LogRecord` doesn't know which request it belongs to. The framework integrations bind each request to a Shipbook **session**, so logs carry the user, client IP, and trace id. Each request is also recorded with its method, route (`/items/{item_id}`), status and duration, and its logs are grouped under it in the Logbook. A failed request (5xx) is always recorded, even if it logged nothing.

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

**Django** (sync and async views) — add to `MIDDLEWARE`, after `SessionMiddleware` and `AuthenticationMiddleware`:

```python
"shipbook.integrations.django.ShipbookMiddleware"
```

Customize each request with extractors (FastAPI/Flask keyword arguments; on Django, subclass and override `get_user`, `get_session_id`, `get_trace_id`, `get_metadata`):

```python
app.add_middleware(
    ShipbookMiddleware,
    user_extractor=lambda request: shipbook.User(user_id=request.headers.get("x-user-id")),
    session_extractor=lambda request: request.cookies.get("login"),  # group requests into one session
    metadata_extractor=lambda request: {"tenant": request.headers.get("x-tenant")},
)
```

Or call `shipbook.register_user(...)` anywhere inside the request. By default every request is its own session; on Django a request joins its Django session when it has one.

**Linked apps.** When a client app with a Shipbook SDK calls your API, it sends an `x-shipbook-session` header. The request joins that client session, so the Logbook shows the whole flow — the app's logs and your server's — in one view.

**JSON-RPC and MCP over HTTP.** A JSON-RPC call is labeled with what it asked for, e.g. `tools/call get-logs`, so calls to one endpoint stay apart.

## MCP servers

For an MCP server built with the `mcp` SDK (2.x), add the middleware and every call becomes a request, labeled with its operation, over any transport (stdio included):

```python
from mcp.server.mcpserver import MCPServer
from shipbook.integrations.mcp import ShipbookMiddleware

server = MCPServer("my-server", middleware=[ShipbookMiddleware()])
```

A tool that fails, raises or returns `isError`, is recorded as a failed request with its JSON-RPC error code.

## Background jobs

Wrap background work so its logs are grouped as a named session:

```python
with shipbook.run_in_context(job_name="nightly-billing"):
    logging.getLogger(__name__).info("charging customers")
```

Anything logged outside a request or job falls back to a per-process background session — nothing is lost.

To read other units of work (a queue message, a scheduled task) the way requests are read, run each one as a request:

```python
with shipbook.run_in_request(shipbook.RequestKind.Rpc, "process order"):
    process(order)
```

It's recorded with its duration and whether it finished or raised.

## Threads and executors

`contextvars` follow `await` and `asyncio` tasks automatically, but a manually
spawned thread or executor starts with a fresh context and would lose the
request's user/IP. Wrap the callable to carry the current context along:

```python
pool.submit(shipbook.preserve_context(do_work))
```

## Crashes and shutdown

An uncaught exception is captured and uploaded before Python prints it and exits, so the crash that killed your process reaches Shipbook. Exceptions in other threads are captured too, and exceptions in `asyncio` tasks arrive through `logging`.

Crashes are grouped in Loglytics by the innermost stack frame of your own code; frames from installed packages and the standard library are skipped. If your app is itself installed as a package (`pip install .`), name it so its frames count as yours:

```python
shipbook.start(app_id="...", app_key="...", in_app_include=["myapp"])
```

Queued logs are uploaded before the process ends: at interpreter exit and on `SIGTERM`/`SIGINT` (a container stop or a deploy), waiting at most 2 seconds. Your own signal handlers still run afterwards, and a default `SIGTERM` still terminates the process. To flush or stop explicitly:

```python
shipbook.flush()      # upload now and wait; flush(timeout=2) to bound it
shipbook.shutdown()
```

Forked workers (for example gunicorn with `--preload`) each upload their own logs.

## Troubleshooting

`shipbook.enable_inner_log(True)` prints the SDK's own diagnostics (login, uploads) to stderr.

## License

MIT
