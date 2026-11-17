# Changelog

## [0.3.0]

### Fixed
- A wrong app key, or a deleted app, no longer makes the SDK log in over and over. It tries once and stays quiet until the next start.
- `register_user()` inside a request or a job now attaches the user to its session.
- Standard-library frames no longer count as your app's code under Homebrew's Python, so a crash is grouped by your own line.
- The SDK no longer silences your console: Python's default printing of warnings and errors keeps working.
- Django's own 4xx warnings ("Not Found: /x") are shown inside their request.

### Added
- FastAPI and Starlette: an exception your endpoint didn't handle is sent as an error of that request, with the line of your code that raised it.
- Django: the signed-in user is attached by itself once your view has read `request.user`.
- `start()` reads your app's version from the nearest `pyproject.toml`.
- An exception raised from another names its cause.
- Type hints ship with the package (`py.typed`).
- `enable_inner_log(True)` reports the login and each upload, not only failures.

## [0.2.0]

### Changed
- Sessions are sent as platform `python`, so the console shows them as Python. Before, they appeared as Node.js.
- Stack frames are sent innermost first, like the other SDKs. This applies to crashes, `logger.exception()` and call stacks.

### Added
- Each stack frame is marked as your app's code or not (the standard library and installed packages are not), so Loglytics groups a crash by its first line in your code. If your app is installed as a package, name it with `start(in_app_include=["myapp"])`.

## [0.1.0]

First release of the Shipbook Python server SDK.

- Ships the standard library `logging` to Shipbook through one `ShipbookHandler`. `shipbook.start(app_id, app_key)` attaches it to the root logger; every `logging` call, with its source location, logger name, thread and traceback, is batched and uploaded by a background thread. Nothing on the request path blocks on the network, and nothing is written to disk.
- Web frameworks (FastAPI/Starlette, Flask, Django): each request is recorded with its method, route, path, client IP, user agent, status and duration, and its logs are grouped under it in the Logbook. Extractors attach the user, group requests into a session, set the trace id and add your own `attributes` (string, number or boolean values). A request carrying a client app's `x-shipbook-session` header joins that session, so the Logbook shows the whole flow.
- JSON-RPC and MCP: a call is labeled with what it asked for (`tools/call get-logs`). `shipbook.integrations.mcp.ShipbookMiddleware` records every call of an `mcp` 2.x server as a request over any transport, and a failed tool as a failed request with its error code.
- `run_in_context(job_name, attributes=...)` runs a background job as its own session and one request, counted in the request totals and error rates. `run_in_request(kind, operation)` reads any other unit of work the same way, and `preserve_context` carries the request context into threads and executors.
- With the Accumulate config, logs below warning are held per request and uploaded only when that request logs a warning or error.
- An uncaught exception is captured and uploaded before Python prints it and exits. Queued logs are uploaded at interpreter exit and on `SIGTERM`/`SIGINT`, waiting at most 2 seconds; `shipbook.flush()` uploads now.
- No runtime dependencies; each framework helper imports its framework only when used.

