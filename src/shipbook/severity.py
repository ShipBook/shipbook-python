import logging
from enum import IntEnum


class Severity(IntEnum):
    """Log severity, matching the Shipbook wire protocol.

    Lower value == more severe. A logger configured at ``Verbose`` ships every
    message whose value is ``<=`` ``Verbose``; ``Error`` ships only errors.
    Serialized over the wire as the member name (e.g. ``"Info"``).
    """

    Off = 0
    Error = 1
    Warning = 2
    Info = 3
    Debug = 4
    Verbose = 5

    @classmethod
    def from_name(cls, name: str) -> "Severity":
        try:
            return cls[name]
        except KeyError:
            return cls.Off

    @classmethod
    def from_logging_level(cls, levelno: int) -> "Severity":
        if levelno >= logging.ERROR:
            return cls.Error
        if levelno >= logging.WARNING:
            return cls.Warning
        if levelno >= logging.INFO:
            return cls.Info
        if levelno >= logging.DEBUG:
            return cls.Debug
        return cls.Verbose
