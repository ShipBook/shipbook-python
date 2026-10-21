"""Real processes against a local fake Shipbook API: what reaches the server when a process
crashes, is terminated, exits, or forks."""

import base64
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


def _config(severity: str) -> dict:
    return {
        "appenders": [
            {
                "type": "SBCloudAppender",
                "name": "cloud",
                "config": {"maxTime": 3, "flushSeverity": severity},
            }
        ],
        "loggers": [{"name": "", "severity": severity, "appenderRef": "cloud"}],
    }


class FakeApi:
    def __init__(self) -> None:
        self.sessions: list[dict] = []
        self.config = _config("Verbose")
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"null")
                if self.path.endswith("auth/loginSdkServer"):
                    payload = json.dumps({"exp": time.time() + 3600}).encode()
                    token = "h." + base64.urlsafe_b64encode(payload).decode().rstrip("=") + ".s"
                    out = {"token": token, "config": api.config}
                else:
                    api.sessions.extend(body["sessions"])
                    out = {"success": True}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v2/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def logs(self) -> list[dict]:
        return [log for s in self.sessions for log in s["logs"]]


@pytest.fixture
def api():
    fake = FakeApi()
    yield fake
    fake.server.shutdown()


def _run(api, tmp_path, body: str) -> subprocess.CompletedProcess:
    script = textwrap.dedent(f"""
        import logging, os, signal, sys, time
        import shipbook
        shipbook.set_connection_url({api.url!r})
        shipbook.start("app", "key")
        log = logging.getLogger("app")
        log.setLevel(logging.DEBUG)
    """) + textwrap.dedent(body)
    env = {**os.environ, "SHIPBOOK_STORAGE_PATH": str(tmp_path)}
    return subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30
    )


def test_a_crash_is_sent_before_the_process_exits(api, tmp_path):
    result = _run(
        api,
        tmp_path,
        """
        log.info("before the crash")
        raise RuntimeError("boom")
    """,
    )

    assert result.returncode == 1
    assert "RuntimeError: boom" in result.stderr
    # Printed once, by Python's own hook.
    assert result.stderr.count("Traceback") == 1
    logs = api.logs()
    assert [log.get("message") for log in logs if log["type"] == "message"] == ["before the crash"]
    crash = next(log for log in logs if log["type"] == "exception")
    assert (crash["name"], crash["reason"]) == ("RuntimeError", "boom")


def test_sigterm_sends_the_queue_then_terminates_the_process(api, tmp_path):
    result = _run(
        api,
        tmp_path,
        """
        log.info("before sigterm")
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(5)
        print("STILL ALIVE")
    """,
    )

    assert result.returncode == -signal.SIGTERM
    assert "STILL ALIVE" not in result.stdout
    assert [log["message"] for log in api.logs()] == ["before sigterm"]


def test_a_short_script_is_sent_at_exit_without_waiting_for_login_at_start(api, tmp_path):
    result = _run(
        api,
        tmp_path,
        """
        log.info("hello and goodbye")
    """,
    )

    assert result.returncode == 0
    assert [log["message"] for log in api.logs()] == ["hello and goodbye"]


def test_a_forked_child_sends_its_own_logs(api, tmp_path):
    result = _run(
        api,
        tmp_path,
        """
        time.sleep(0.5)  # logged in, as a preloaded gunicorn master is before it forks
        log.info("from the parent")
        pid = os.fork()
        if pid == 0:
            log.info("from the child")
            shipbook.flush(5)
            os._exit(0)
        os.waitpid(pid, 0)
    """,
    )

    assert result.returncode == 0, result.stderr
    messages = [log["message"] for log in api.logs()]
    # Each process sends its own queue: the child doesn't resend the parent's log.
    assert sorted(messages) == ["from the child", "from the parent"]


def test_logs_before_login_are_filtered_by_the_apps_own_config(api, tmp_path):
    api.config = _config("Warning")
    result = _run(api, tmp_path, """
        log.info("filtered out by the app's config")
        log.warning("kept")
    """)

    assert result.returncode == 0, result.stderr
    assert [log["message"] for log in api.logs()] == ["kept"]
