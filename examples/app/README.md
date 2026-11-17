# Example app: an orders service

A small service that uses the whole SDK, the Python counterpart of `examples/node-app` in
[shipbook-js](https://github.com/ShipBook/shipbook-js). Run it against your own Shipbook app
and read the result in the [console](https://console.shipbook.io).

| File | What it shows |
|---|---|
| `api.py` | A FastAPI service: every request with its user, attributes, status and duration; requests that share a login cookie read as one session; a JSON-RPC endpoint; work handed to another thread with `preserve_context` |
| `traffic.py` | Calls the API the way its clients would: healthy requests, a warning, a 404 and a 500 |
| `jobs.py` | Background jobs (`run_in_context`), queue messages (`run_in_request`), and exceptions in a thread and in an `asyncio` task |
| `crash.py` | An uncaught exception, sent before the process exits |
| `common.py` | `shipbook.start()` with the credentials from `.env` |

## Run it

```bash
cd examples/app
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your app's id and key
```

```bash
uvicorn api:app --port 3001     # terminal 1
python traffic.py               # terminal 2
python jobs.py
python crash.py
```

In the console's Logbook, each request and each job run is a group of its own. Sam's requests
share one session, the failed refund is marked as an error, and the crash shows its stack.

## Session-linking demo

`api.py` answers `POST /api/orders` the way the Express backend of the
[session-linking demo](https://github.com/ShipBook/shipbook-js/tree/master/examples) does, so
the browser shop there works with this backend unchanged: start `uvicorn api:app --port 3001`
instead of `npm run start:shop`. The shop's session in the console then shows this service's
request and its logs inline.
