from dataclasses import dataclass, field
from typing import Any, Optional

from .user import User


@dataclass
class DeviceInfo:
    udid: str
    os: str
    device_name: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"udid": self.udid, "os": self.os}
        if self.device_name is not None:
            d["deviceName"] = self.device_name
        return d


@dataclass
class Session:
    """One logical unit of work — an HTTP request or a background job — that
    logs are grouped under on the server (via ``sessionId``)."""

    session_id: str
    platform: str
    time: str
    device_info: DeviceInfo
    os_name: str
    os_version: str
    sdk_version: str
    app_version: Optional[str] = None
    user: Optional[User] = None
    metadata: Optional[dict[str, Any]] = None
    is_background: bool = False
    job_name: Optional[str] = None
    caller_session_link: Optional[str] = None
    logs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "sessionId": self.session_id,
            "platform": self.platform,
            "time": self.time,
            "deviceInfo": self.device_info.to_dict(),
            "os": {"name": self.os_name, "version": self.os_version},
            "appInfo": {"version": self.app_version},
            "sdkInfo": {"version": self.sdk_version},
            "isBackground": self.is_background,
            "logs": self.logs,
        }
        if self.user is not None:
            d["userInfo"] = self.user.to_dict()
        if self.metadata is not None:
            d["metadata"] = self.metadata
        if self.job_name is not None:
            d["jobName"] = self.job_name
        if self.caller_session_link is not None:
            d["callerSessionLink"] = self.caller_session_link
        return d
