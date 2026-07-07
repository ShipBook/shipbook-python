import logging
import threading
from typing import Optional

from . import _state
from .cloud_uploader import CloudUploader
from .config import Config
from .connection_client import ConnectionClient
from .handler import ShipbookHandler
from .hooks import exception_handler, exit_handler
from .session_manager import SessionManager
from .storage import Storage

_logger = logging.getLogger("shipbook")


class _Runtime:
    def __init__(self, app_id: str, app_key: str, app_version: Optional[str]) -> None:
        self._app_id = app_id
        self._app_key = app_key

        self.storage = Storage()
        self.connection = ConnectionClient()
        self.session_manager = SessionManager(self.connection)
        self.connection.set_deps(
            get_token=self.session_manager.get_token,
            refresh_token=self.session_manager.refresh,
        )

        persisted = self.storage.get_obj("config")
        self.config = Config.from_dict(persisted) if persisted else Config.default()

        self.uploader = CloudUploader(
            self.connection, self.session_manager, self.storage, self.config, app_version
        )
        self.handler = ShipbookHandler()
        self.session_manager.on_config = self._apply_config
        self._config_timer: Optional[threading.Timer] = None
        self._closed = False

    def start(self) -> None:
        config_dict = self.session_manager.login(self._app_id, self._app_key)
        if config_dict is None:
            _logger.warning("Shipbook auth failed — logs will buffer until it succeeds")
            return
        self._apply_config(config_dict)
        self._schedule_config_refresh(self.config.config_refresh_interval)

    def _apply_config(self, config_dict: dict) -> None:
        self.config = Config.from_dict(config_dict)
        self.uploader.set_config(self.config)
        self.storage.set_obj("config", config_dict)

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
        self._schedule_config_refresh(self.config.config_refresh_interval)

    def shutdown(self) -> None:
        self._closed = True
        if self._config_timer:
            self._config_timer.cancel()
        self.session_manager.destroy()
        self.uploader.shutdown()


_runtime: Optional[_Runtime] = None
_lock = threading.Lock()


def start(
    app_id: str,
    app_key: str,
    app_version: Optional[str] = None,
    *,
    attach_to_root: bool = True,
    capture_level: Optional[int] = None,
    install_hooks: bool = True,
) -> None:
    """Log in to Shipbook and start shipping logs.

    By default this attaches a :class:`ShipbookHandler` to the root logger, so
    every ``logging`` call in the process flows to Shipbook (gated by the
    server-side config). Standard ``logging`` levels still apply — if you want
    to ship DEBUG/INFO, make sure the relevant logger's level allows them (or
    pass ``capture_level=logging.DEBUG`` to set the root logger level).
    """
    global _runtime
    with _lock:
        if _runtime is not None:
            _logger.warning("shipbook.start() called more than once — ignoring")
            return
        runtime = _Runtime(app_id, app_key, app_version)
        _runtime = runtime
        _state.set_active(runtime)

    if capture_level is not None:
        logging.getLogger().setLevel(capture_level)
    if attach_to_root:
        logging.getLogger().addHandler(runtime.handler)
    if install_hooks:
        exception_handler.install()
        exit_handler.install(flush)

    runtime.start()


def get_handler() -> Optional[ShipbookHandler]:
    """The handler, e.g. to attach to a specific logger instead of the root."""
    return _runtime.handler if _runtime else None


def flush() -> None:
    if _runtime:
        _runtime.uploader.flush()


def set_connection_url(url: str) -> None:
    if _runtime:
        _runtime.connection.set_base_url(url)


def shutdown() -> None:
    global _runtime
    with _lock:
        runtime = _runtime
        if runtime is None:
            return
        _runtime = None
        _state.set_active(None)
    logging.getLogger().removeHandler(runtime.handler)
    exception_handler.uninstall()
    runtime.shutdown()
