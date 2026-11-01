# Changelog

## [0.1.0]

First release of the Shipbook Python server SDK.

- Ships the standard library `logging` to Shipbook through one `ShipbookHandler`. `shipbook.start(app_id, app_key)` attaches it to the root logger; every `logging` call, with its source location, logger name, thread and traceback, is batched and uploaded by a background thread. Nothing on the request path blocks on the network, and nothing is written to disk.
- Web frameworks (FastAPI/Starlette, Flask, Django): each request is recorded with its method, route, path, client IP, user agent, status and duration, and its logs are grouped under it in the Logbook. Extractors attach the user, group requests into a session, set the trace id and add your own `attributes` (string, number or boolean values). A request carrying a client app's `x-shipbook-session` header joins that session, so the Logbook shows the whole flow.
- JSON-RPC and MCP: a call is labeled with what it asked for (`tools/call get-logs`). `shipbook.integrations.mcp.ShipbookMiddleware` records every call of an `mcp` 2.x server as a request over any transport, and a failed tool as a failed request with its error code.
- `run_in_context(job_name, attributes=...)` runs a background job as its own session and one request, counted in the request totals and error rates. `run_in_request(kind, operation)` reads any other unit of work the same way, and `preserve_context` carries the request context into threads and executors.
- With the Accumulate config, logs below warning are held per request and uploaded only when that request logs a warning or error.
- An uncaught exception is captured and uploaded before Python prints it and exits. Queued logs are uploaded at interpreter exit and on `SIGTERM`/`SIGINT`, waiting at most 2 seconds; `shipbook.flush()` uploads now.
- No runtime dependencies; each framework helper imports its framework only when used.

