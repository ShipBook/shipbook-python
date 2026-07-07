# Changelog

## [0.1.0]

- Initial release of the Shipbook Python server SDK.
- Ships the standard library `logging` to Shipbook via a single `ShipbookHandler` — no separate logging API.
- Server-SDK transport: `loginSdkServer` auth with 80%-lifetime token refresh, periodic config refresh, and background-thread batching to `sessions/ingest`, with a disk-persisted queue that survives restarts.
- Per-request context binding (user, client IP, trace id) via `contextvars`, with FastAPI/Starlette, Flask, and Django integrations.
- `run_in_context` for background jobs, `preserve_context` for offloading work to threads/executors, and automatic flush on exit and uncaught exceptions.
