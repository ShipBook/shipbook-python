import platform as _platform
import socket
import threading
import uuid
from typing import Optional

from . import context
from ._util import to_iso
from .config import Config
from .connection_client import ConnectionClient
from .generated.version import SDK_VERSION
from .models.message import Message
from .models.request_context import RequestContext
from .models.session import DeviceInfo, Session
from .session_manager import SessionManager

QUEUE_KEY = "session_queue"
MACHINE_UDID_KEY = "machine_udid"

# The server Platform enum has no "python" value yet, so sessions ride in as
# "node" to be accepted by ingest. See the SDK plan's open item.
_PLATFORM = "node"


class CloudUploader:
    """Batches logs and ships them to ``sessions/ingest`` on a background
    daemon thread. Port of the node SBCloudAppender without the appender
    abstraction — the only destination the Python SDK has."""

    def __init__(
        self,
        connection: ConnectionClient,
        session_manager: SessionManager,
        storage,
        config: Config,
        app_version: Optional[str] = None,
        start_worker: bool = True,
    ) -> None:
        self._connection = connection
        self._session_manager = session_manager
        self._storage = storage
        self._config = config
        self._app_version = app_version

        self._device_info = DeviceInfo(
            udid=self._init_udid(), os=_PLATFORM, device_name=socket.gethostname()
        )
        self._os_name = _platform.system()
        self._os_version = _platform.release()
        self._sdk_version = f"python:{SDK_VERSION}"

        self._emitted: set = set()
        self._emitted_lock = threading.Lock()

        self._cond = threading.Condition()
        self._flush_now = False
        self._stopped = False
        self._pending = 0

        self._background_context = RequestContext(
            session_id=str(uuid.uuid4()),
            is_background=True,
            metadata={"type": "background"},
        )

        self._thread: Optional[threading.Thread] = None
        if start_worker:
            self._thread = threading.Thread(
                target=self._run, name="shipbook-uploader", daemon=True
            )
            self._thread.start()

    def set_config(self, config: Config) -> None:
        self._config = config

    def push(self, message: Message) -> None:
        ctx = context.get() or self._background_context
        self.ensure_session(ctx)

        record = message.to_dict()
        if ctx.trace_id:
            record["traceId"] = ctx.trace_id
        self._storage.push_array_obj(
            QUEUE_KEY, {"type": "log", "sessionId": ctx.session_id, "data": record}
        )
        self._schedule_flush(message.severity)

    def ensure_session(self, ctx: RequestContext) -> None:
        """Emit a session descriptor once per flush window so sessions whose
        logs are all below the immediate-flush severity still reach the
        server."""
        with self._emitted_lock:
            if ctx.session_id in self._emitted:
                return
            self._emitted.add(ctx.session_id)

        session = Session(
            session_id=ctx.session_id,
            platform=_PLATFORM,
            time=to_iso(ctx.start_time),
            device_info=self._device_info,
            os_name=self._os_name,
            os_version=self._os_version,
            sdk_version=self._sdk_version,
            app_version=self._app_version,
            user=ctx.user,
            metadata=ctx.metadata,
            is_background=ctx.is_background,
            job_name=ctx.job_name,
        )
        self._storage.push_array_obj(
            QUEUE_KEY,
            {"type": "session", "sessionId": ctx.session_id, "data": session.to_dict()},
        )

    def flush(self) -> None:
        with self._cond:
            self._flush_now = True
            self._cond.notify()

    def shutdown(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify()
        if self._thread is not None:
            self._thread.join(timeout=self._config.max_time + 5)
        else:
            self._send()

    def _schedule_flush(self, severity) -> None:
        with self._cond:
            self._pending += 1
            over_size = self._pending >= self._config.flush_size
        if severity.value <= self._config.flush_severity.value or over_size:
            self.flush()

    def _run(self) -> None:
        while True:
            with self._cond:
                if not self._flush_now and not self._stopped:
                    self._cond.wait(timeout=self._config.max_time)
                stopped = self._stopped
                self._flush_now = False
            self._send()
            if stopped:
                return

    def _send(self) -> None:
        if not self._session_manager.get_token():
            return
        records = self._storage.pop_all_array_obj(QUEUE_KEY)
        with self._emitted_lock:
            self._emitted.clear()
        with self._cond:
            self._pending = 0
        if not records:
            return

        sessions: dict[str, dict] = {}
        for r in records:
            if r.get("type") == "session":
                sessions[r["sessionId"]] = r["data"]
        for r in records:
            if r.get("type") == "log":
                session = sessions.get(r["sessionId"])
                if session is not None:
                    session["logs"].append(r["data"])

        payload = {"sessions": list(sessions.values())}
        resp = self._connection.request("sessions/ingest", payload, "POST")
        if not resp.ok:
            # Re-queue for the next window. Server upserts sessions by sessionId,
            # so re-sending a descriptor is safe.
            for r in records:
                self._storage.push_array_obj(QUEUE_KEY, r)

    def _init_udid(self) -> str:
        stored = self._storage.get_item(MACHINE_UDID_KEY)
        if stored:
            return stored.strip()
        udid = str(uuid.uuid4())
        self._storage.set_item(MACHINE_UDID_KEY, udid)
        return udid
