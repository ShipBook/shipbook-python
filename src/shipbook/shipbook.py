import contextvars
import logging
import os
import threading
import time
from collections.abc import Iterable
from typing import Callable, Optional

from . import _state
from ._inner_log import inner_log
from .cloud_uploader import CloudUploader
from .config import DEFAULT_CONFIG_REFRESH_INTERVAL, Config
from .connection_client import ConnectionClient
from .handler import ShipbookHandler
from .hooks import exception_handler, exit_handler
from .models.exception import ExceptionLog
from .models.frames import set_in_app_include
from .session_manager import SessionManager
from .storage import Storage

# How long a process waits for its last upload before it ends, as Sentry's shutdownTimeout.
BEFORE_EXIT_TIMEOUT = 2.0
# The same cap as the cloud queue's max_log_size, for what's held until the first server config.
STARTUP_HOLD_LIMIT = 5000


class _Runtime:
    def __init__(
        self, app_id: str, app_key: str, app_version: Optional[str], connection_url: Optional[str]
    ) -> None:
        self._app_id = app_id
        self._app_key = app_key
        # Per app: apps on one machine share storage; none may start with another's config.
        self._config_key = f"config_{app_id}"

        self.storage = Storage()
        self.connection = ConnectionClient()
        if connection_url:
            self.connection.set_base_url(connection_url)
        self.session_manager = SessionManager(self.connection)
        self.connection.set_deps(
            get_token=self.session_manager.get_token,
            refresh_token=self.session_manager.refresh,
        )

        # None until the first server config (cached or from login): a guessed default would
        # ship what the app's config filters out, so until then everything is held for it.
        self.config: Optional[Config] = None
        self._held: list[tuple[contextvars.Context, Callable[[], None]]] = []
        self._hold_lock = threading.Lock()

        # The uploader acts only on what passed a real config; this one is replaced before any.
        self.uploader = CloudUploader(
            self.connection, self.session_manager, self.storage, Config.default(), app_version
        )
        self.handler = ShipbookHandler()
        self.session_manager.on_config = self._on_login
        self._config_timer: Optional[threading.Timer] = None
        self._refresh_interval = DEFAULT_CONFIG_REFRESH_INTERVAL
        self._closed = False
        # Set once the first login attempt has finished, either way; the exit paths wait for it.
        self.login_done = threading.Event()

        persisted = self.storage.get_obj(self._config_key)
        if persisted:
            self._apply_config(persisted)

    def when_configured(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` now, or, before the first server config, once it arrives, in this context."""
        with self._hold_lock:
            if self.config is None:
                self._held.append((contextvars.copy_context(), fn))
                if len(self._held) > STARTUP_HOLD_LIMIT:
                    del self._held[0]
                return
        fn()

    def start(self) -> None:
        # Off the caller's thread: an unreachable API mustn't block startup. Logs queue meanwhile.
        threading.Thread(target=self._login, name="shipbook-login", daemon=True).start()

    def _login(self) -> None:
        try:
            config_dict = self.session_manager.login(self._app_id, self._app_key)
            if config_dict is None:
                inner_log.warning("auth failed - logs queue until it succeeds")
                return
            self._on_login(config_dict)
            self._schedule_config_refresh(self._refresh_interval)
        finally:
            self.login_done.set()

    def _on_login(self, config_dict: dict) -> None:
        self._apply_config(config_dict)
        # What was queued before the token arrived goes up now.
        self.uploader.request_send()

    def _apply_config(self, config_dict: dict) -> None:
        config = Config.from_dict(config_dict)
        with self._hold_lock:
            self.config = config
            self._refresh_interval = config.config_refresh_interval
            self.uploader.set_config(config)
            held, self._held = self._held, []
        self.storage.set_obj(self._config_key, config_dict)
        # The first config also takes what was held, each in the context it was logged in.
        for ctx, fn in held:
            ctx.run(fn)

    def _schedule_config_refresh(self, interval: int) -> None:
        if self._closed:
            return
        if self._config_timer:
            self._config_timer.cancel()
        self._config_timer = threading.Timer(interval, self._refresh_config)
        self._config_timer.daemon = True
        self._config_timer.start()

    def _refresh_config(self) -> None:
        resp = self.connection.request("auth/configSdkServer", None, "GET")
        if resp.ok and resp.data:
            self._apply_config(resp.data)
        self._schedule_config_refresh(self._refresh_interval)

    def capture_exception(self, exception: ExceptionLog, fatal: bool) -> None:
        def push() -> None:
            if self.config is not None and self.config.cloud_enabled:
                self.uploader.push(exception)

        self.when_configured(push)
        # The process ends right after a fatal one, so it's sent now instead of on the timer.
        if fatal:
            self.flush(BEFORE_EXIT_TIMEOUT)

    def flush(self, timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        self.login_done.wait(timeout)
        remaining = None if deadline is None else max(deadline - time.monotonic(), 0)
        return self.uploader.flush(remaining)

    def after_fork(self) -> None:
        self._hold_lock = threading.Lock()
        self.uploader.after_fork()
        self.session_manager.after_fork()
        self._config_timer = None
        if self.login_done.is_set():
            self._schedule_config_refresh(self._refresh_interval)

    def shutdown(self) -> None:
        self._closed = True
        if self._config_timer:
            self._config_timer.cancel()
        self.login_done.wait()
        self.session_manager.destroy()
        self.uploader.shutdown()


_runtime: Optional[_Runtime] = None
_lock = threading.Lock()
_connection_url: Optional[str] = None


def start(
    app_id: str,
    app_key: str,
    app_version: Optional[str] = None,
    *,
    attach_to_root: bool = True,
    capture_level: Optional[int] = None,
    install_hooks: bool = True,
    in_app_include: Iterable[str] = (),
) -> None:
    """Start shipping logs. Returns at once: login runs in the background, logs queue meanwhile.

    By default this attaches a :class:`ShipbookHandler` to the root logger, so
    every ``logging`` call in the process flows to Shipbook (gated by the
    server-side config). Standard ``logging`` levels still apply — if you want
    to ship DEBUG/INFO, make sure the relevant logger's level allows them (or
    pass ``capture_level=logging.DEBUG`` to set the root logger level).

    With ``install_hooks`` it also captures uncaught exceptions, and sends what's
    queued before the process ends (exit, SIGTERM, SIGINT), waiting at most 2 seconds.

    Stack frames from installed packages and the standard library aren't the app's own,
    which Loglytics uses to group crashes. If your app is itself installed as a package
    (``pip install .``), name it in ``in_app_include``.
    """
    global _runtime
    with _lock:
        if _runtime is not None:
            inner_log.warning("shipbook.start() called more than once - ignoring")
            return
        runtime = _Runtime(app_id, app_key, app_version, _connection_url)
        _runtime = runtime
        _state.set_active(runtime)

    set_in_app_include(in_app_include)
    if capture_level is not None:
        logging.getLogger().setLevel(capture_level)
    if attach_to_root:
        logging.getLogger().addHandler(runtime.handler)
    if install_hooks:
        exception_handler.install(runtime.capture_exception)
        exit_handler.install(lambda: runtime.flush(BEFORE_EXIT_TIMEOUT))

    runtime.start()


def get_handler() -> Optional[ShipbookHandler]:
    """The handler, e.g. to attach to a specific logger instead of the root."""
    return _runtime.handler if _runtime else None


def flush(timeout: Optional[float] = None) -> bool:
    """Send what's queued now and wait, at most ``timeout`` seconds. True when it finished."""
    return _runtime.flush(timeout) if _runtime else True


def set_connection_url(url: str) -> None:
    """Point the SDK at another Shipbook API (e.g. staging). Call it before :func:`start`."""
    global _connection_url
    _connection_url = url
    if _runtime:
        _runtime.connection.set_base_url(url)


def shutdown() -> None:
    """Stop capturing and send what's queued, waiting for it."""
    global _runtime
    with _lock:
        runtime = _runtime
        if runtime is None:
            return
        _runtime = None
        _state.set_active(None)
    logging.getLogger().removeHandler(runtime.handler)
    exception_handler.uninstall()
    exit_handler.uninstall()
    runtime.shutdown()


def _after_fork_in_child() -> None:
    global _lock
    # The parent's threads don't exist in the child, and a lock one of them held stays held.
    _lock = threading.Lock()
    if _runtime is not None:
        _runtime.after_fork()


# Unix only: Windows has no fork.
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)
