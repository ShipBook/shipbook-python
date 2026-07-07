"""FastAPI app whose per-request logs are grouped into Shipbook sessions.

Run:  SHIPBOOK_APP_ID=... SHIPBOOK_APP_KEY=... uvicorn examples.fastapi_app:app
"""

import logging
import os
from typing import Optional

from fastapi import FastAPI

import shipbook
from shipbook import User
from shipbook.integrations.fastapi import ShipbookMiddleware

shipbook.start(
    app_id=os.environ["SHIPBOOK_APP_ID"],
    app_key=os.environ["SHIPBOOK_APP_KEY"],
    capture_level=logging.INFO,
)

app = FastAPI()


def extract_user(request) -> Optional[User]:
    user_id = request.headers.get("x-user-id")
    return User(user_id=user_id) if user_id else None


app.add_middleware(ShipbookMiddleware, user_extractor=extract_user)

log = logging.getLogger("example.api")


@app.get("/hello")
def hello():
    log.info("handling /hello")
    return {"ok": True}


@app.get("/boom")
def boom():
    log.info("about to fail")
    raise RuntimeError("intentional error")
