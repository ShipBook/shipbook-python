import platform as _platform
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Union
from weakref import WeakKeyDictionary

from . import context
from ._inner_log import inner_log
from ._util import to_iso
from .config import Config
from .connection_client import ConnectionClient
from .generated.version import SDK_VERSION
from .models.exception import ExceptionLog
from .models.message import Message
from .models.request_context import RequestContext
from .models.request_event import RequestEvent, RequestEventPhase, RequestOutcome
from .models.session import DeviceInfo, Session
from .session_manager import SessionManager

MACHINE_UDID_KEY = "machine_udid"

# The server Platform enum has no "python" value yet, so sessions ride in as
# "node" to be accepted by ingest.
_PLATFORM = "node"

Log = Union[Message, ExceptionLog, RequestEvent]


# Mobile's flushQueue, one per request: it goes up only with a log at or above flush_severity.
@dataclass
class _FlushQueue:
    logs: list[dict[str, Any]] = field(default_factory=list)
    saved: bool = False


class CloudUploader:
    """Ships logs to ``sessions/ingest`` the way the mobile and Node SDKs do.

    - Logs below ``flush_severity`` (and request events) wait in their request's flushQueue
      and are saved only as the context of a later log at or above it (Accumulate).
    - Saved logs go into an in-memory cloud queue: sessions keyed by id, each collecting
      its logs. Nothing is written to disk, and each process has its own queue.
    - A background thread uploads the queue ``max_time`` after the first save, or at once
      when it holds ``max_batch_size`` items. A burst of errors is one upload.
    """

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
        self._start_worker = start_worker
        self._reset_state()

    def _reset_state(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        # One upload at a time; also what flush() waits on.
        self._send_lock = threading.Lock()
        self._cloud_queue: dict[str, dict[str, Any]] = {}
        # Sessions in the cloud queue plus their logs: what max_batch_size and max_log_size measure.
        self._queue_size = 0
        # Keyed by context object: freed with the request, also when it never finishes.
        self._flush_queues: WeakKeyDictionary[RequestContext, _FlushQueue] = WeakKeyDictionary()
        self._deadline: Optional[float] = None
        self._send_now = False
        self._stopped = False
        # One background session per process, for logs and requests outside any other context.
        self.background_context = RequestContext(session_id=str(uuid.uuid4()), is_background=True)
        self._thread: Optional[threading.Thread] = None
        if self._start_worker:
            self._thread = threading.Thread(target=self._run, name="shipbook-uploader", daemon=True)
            self._thread.start()

    def after_fork(self) -> None:
        """In a forked child: the parent's thread is gone, its locks may be held."""
        self._reset_state()

    def set_config(self, config: Config) -> None:
        self._config = config

    def push(self, log: Log) -> None:
        ctx = context.get() or self.background_context
        data = log.to_dict()
        if ctx.trace_id:
            data["traceId"] = ctx.trace_id
        if ctx.request_id:
            data["requestId"] = ctx.request_id
            # requestTime keeps a request's logs contiguous in the server's display-order sort.
            data["requestTime"] = to_iso(ctx.start_time)

        with self._lock:
            session = self._session(ctx)
            flush_queue = self._flush_queues.get(ctx)
            if flush_queue is None:
                flush_queue = self._flush_queues[ctx] = _FlushQueue()

            if self._is_held(log, flush_queue):
                flush_queue.logs.append(data)
                if len(flush_queue.logs) > self._config.flush_size:
                    del flush_queue.logs[0]
                return

            # The flushQueue is this log's context: it is saved with it, in order.
            saved = [*flush_queue.logs, data]
            session["logs"].extend(saved)
            self._queue_size += len(saved)
            flush_queue.logs = []
            flush_queue.saved = True
            self._after_save()

    def start_request(self, ctx: RequestContext) -> None:
        """A request began in ``ctx``: queue its session and count it, whether or not it logs.
        Counted on the session, not as a log, so the server adds it up and a request whose
        logs all stay below flush_severity still counts."""
        with self._lock:
            self._session(ctx)["requests"] += 1

    def _session(self, ctx: RequestContext) -> dict[str, Any]:
        if self._queue_size >= self._config.max_log_size:
            inner_log.debug("cloud queue over max_log_size, dropping it")
            self._cloud_queue.clear()
            self._queue_size = 0
        queued = self._cloud_queue.get(ctx.session_id)
        if queued is not None:
            return queued

        session = self._cloud_queue[ctx.session_id] = Session(
            session_id=ctx.session_id,
            platform=_PLATFORM,
            time=to_iso(ctx.start_time),
            device_info=self._device_info,
            os_name=self._os_name,
            os_version=self._os_version,
            sdk_version=self._sdk_version,
            app_version=self._app_version,
            user=ctx.user,
            attributes=ctx.attributes,
            is_background=ctx.is_background,
            job_name=ctx.job_name,
            caller_session_link=ctx.caller_session_link,
        ).to_dict()
        self._queue_size += 1
        self._after_save()
        return session

    def _is_held(self, log: Log, flush_queue: _FlushQueue) -> bool:
        if isinstance(log, Message):
            return self._config.flush_severity.value < log.severity.value
        # A process keeps running after an exception: it's saved like an error, the timer sends it.
        if isinstance(log, ExceptionLog):
            return False
        if log.event == RequestEventPhase.End:
            # A failed request is saved like an error, start included, even if it logged nothing.
            if log.outcome == RequestOutcome.Error:
                return False
            # A request whose logs went up keeps its end: it has the status, outcome, duration.
            return not flush_queue.saved
        return True

    def _after_save(self) -> None:
        if self._queue_size >= self._config.max_batch_size:
            self._send_now = True
            self._wake.notify()
        elif self._deadline is None:
            self._deadline = time.monotonic() + self._config.max_time
            self._wake.notify()

    def request_send(self) -> None:
        """Wake the worker to send now, without waiting (e.g. once login has succeeded)."""
        with self._lock:
            self._send_now = True
            self._wake.notify()

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Send what's queued now and wait, at most ``timeout`` seconds. True when it finished."""
        if timeout is None:
            self._send()
            return True
        sender = threading.Thread(target=self._send, name="shipbook-flush", daemon=True)
        sender.start()
        sender.join(timeout)
        return not sender.is_alive()

    def shutdown(self, timeout: Optional[float] = None) -> None:
        with self._lock:
            self._stopped = True
            self._wake.notify()
        if self._thread is not None:
            self._thread.join(1)
        self.flush(timeout)

    def _run(self) -> None:
        while True:
            with self._lock:
                while not self._due():
                    wait = (
                        None
                        if self._deadline is None
                        else max(self._deadline - time.monotonic(), 0)
                    )
                    self._wake.wait(wait)
                if self._stopped:
                    return
            self._send()

    def _due(self) -> bool:
        if self._stopped or self._send_now:
            return True
        return self._deadline is not None and time.monotonic() >= self._deadline

    def _send(self) -> None:
        with self._send_lock:
            with self._lock:
                self._deadline = None
                self._send_now = False
                # No token: the queue stays (bounded by max_log_size) and a login sends it.
                if not self._session_manager.get_token():
                    return
                sessions = list(self._cloud_queue.values())
                self._cloud_queue = {}
                self._queue_size = 0
            if not sessions:
                return

            resp = self._connection.request("sessions/ingest", {"sessions": sessions}, "POST")
            if resp.ok:
                return
            inner_log.error("ingest failed: %s %s", resp.status, resp.text[:200])
            # Unreachable or a server error: retry next window. A 4xx would fail the same way again.
            if resp.status == 0 or resp.status >= 500:
                self._requeue(sessions)

    def _requeue(self, sessions: list[dict[str, Any]]) -> None:
        with self._lock:
            for session in sessions:
                queued = self._cloud_queue.get(session["sessionId"])
                if queued is None:
                    self._cloud_queue[session["sessionId"]] = session
                    self._queue_size += 1 + len(session["logs"])
                else:
                    queued["logs"][:0] = session["logs"]
                    queued["requests"] += session["requests"]
                    self._queue_size += len(session["logs"])
            if self._deadline is None:
                self._deadline = time.monotonic() + self._config.max_time
                self._wake.notify()

    def _init_udid(self) -> str:
        stored = self._storage.get_item(MACHINE_UDID_KEY)
        if stored:
            return stored.strip()
        udid = str(uuid.uuid4())
        self._storage.set_item(MACHINE_UDID_KEY, udid)
        return udid
