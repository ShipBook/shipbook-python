"""Flask app whose per-request logs are grouped into Shipbook sessions.

Run:  SHIPBOOK_APP_ID=... SHIPBOOK_APP_KEY=... flask --app examples.flask_app run
"""

import logging
import os

from flask import Flask

import shipbook
from shipbook.integrations.flask import init_app

shipbook.start(
    app_id=os.environ["SHIPBOOK_APP_ID"],
    app_key=os.environ["SHIPBOOK_APP_KEY"],
    capture_level=logging.INFO,
)

app = Flask(__name__)
init_app(app)

log = logging.getLogger("example.flask")


@app.route("/hello")
def hello():
    log.info("handling /hello")
    return {"ok": True}
