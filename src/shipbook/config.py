from dataclasses import dataclass, field
from typing import Any, Optional

from .severity import Severity

# Appender types that mean "ship to Shipbook cloud". Console output on Python is
# the user's own logging handlers' job, so only cloud loggers gate what we send.
_CLOUD_TYPES = {"SBCloudAppender", "SLCloudAppender"}

DEFAULT_MAX_TIME = 3.0
DEFAULT_FLUSH_SIZE = 100  # per request, not per app as on mobile
DEFAULT_MAX_BATCH_SIZE = 1000
DEFAULT_MAX_LOG_SIZE = 5000
DEFAULT_CONFIG_REFRESH_INTERVAL = 300


@dataclass
class _Logger:
    key: str
    severity: Severity
    call_stack_severity: Severity


@dataclass
class Config:
    """Parsed server config. Holds only what the Python SDK acts on: which
    tags/severities ship to cloud, and the cloud appender's flush knobs."""

    loggers: list[_Logger] = field(default_factory=list)
    max_time: float = DEFAULT_MAX_TIME
    flush_severity: Severity = Severity.Warning
    # Ring size of a request's flushQueue: logs held below flush_severity, as error context.
    flush_size: int = DEFAULT_FLUSH_SIZE
    # A server saves thousands within max_time: an upload also goes once the queue holds this many.
    max_batch_size: int = DEFAULT_MAX_BATCH_SIZE
    # While uploads can't drain the queue (no token, server down) it's emptied at this size.
    max_log_size: int = DEFAULT_MAX_LOG_SIZE
    config_refresh_interval: int = DEFAULT_CONFIG_REFRESH_INTERVAL
    raw: Optional[dict[str, Any]] = None

    @classmethod
    def default(cls) -> "Config":
        return cls.from_dict(
            {
                "appenders": [
                    {
                        "type": "SBCloudAppender",
                        "name": "cloud",
                        "config": {"maxTime": DEFAULT_MAX_TIME, "flushSeverity": "Warning"},
                    }
                ],
                "loggers": [{"name": "", "severity": "Verbose", "appenderRef": "cloud"}],
            }
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        appenders = data.get("appenders") or []
        cloud_names = {a.get("name") for a in appenders if a.get("type") in _CLOUD_TYPES}

        cloud_cfg: dict[str, Any] = {}
        for a in appenders:
            if a.get("type") in _CLOUD_TYPES and a.get("config"):
                cloud_cfg = a["config"]
                break

        loggers = [
            _Logger(
                key=lg.get("name") or "",
                severity=Severity.from_name(lg.get("severity", "Off")),
                call_stack_severity=Severity.from_name(lg.get("callStackSeverity", "Off")),
            )
            for lg in (data.get("loggers") or [])
            if lg.get("appenderRef") in cloud_names
        ]

        cfg = cls(loggers=loggers, raw=data)
        if cloud_cfg.get("maxTime") is not None:
            cfg.max_time = float(cloud_cfg["maxTime"])
        if cloud_cfg.get("flushSeverity"):
            cfg.flush_severity = Severity.from_name(cloud_cfg["flushSeverity"])
        if cloud_cfg.get("flushSize") is not None:
            cfg.flush_size = int(cloud_cfg["flushSize"])
        if cloud_cfg.get("maxBatchSize") is not None:
            cfg.max_batch_size = int(cloud_cfg["maxBatchSize"])
        if cloud_cfg.get("maxLogSize") is not None:
            cfg.max_log_size = int(cloud_cfg["maxLogSize"])
        if data.get("configRefreshInterval") is not None:
            cfg.config_refresh_interval = int(data["configRefreshInterval"])
        return cfg

    @property
    def cloud_enabled(self) -> bool:
        return any(lg.severity != Severity.Off for lg in self.loggers)

    def should_ship(self, tag: str, severity: Severity) -> bool:
        threshold = Severity.Off
        for lg in self.loggers:
            if tag.startswith(lg.key) and lg.severity.value > threshold.value:
                threshold = lg.severity
        return threshold != Severity.Off and severity.value <= threshold.value

    def call_stack_severity(self, tag: str) -> Severity:
        result = Severity.Off
        for lg in self.loggers:
            if tag.startswith(lg.key) and lg.call_stack_severity.value > result.value:
                result = lg.call_stack_severity
        return result
