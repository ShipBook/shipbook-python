import logging

from shipbook.config import Config
from shipbook.severity import Severity


def test_logging_level_to_severity():
    assert Severity.from_logging_level(logging.CRITICAL) is Severity.Error
    assert Severity.from_logging_level(logging.ERROR) is Severity.Error
    assert Severity.from_logging_level(logging.WARNING) is Severity.Warning
    assert Severity.from_logging_level(logging.INFO) is Severity.Info
    assert Severity.from_logging_level(logging.DEBUG) is Severity.Debug
    assert Severity.from_logging_level(5) is Severity.Verbose


def test_severity_from_name_unknown_is_off():
    assert Severity.from_name("Nope") is Severity.Off
    assert Severity.from_name("Warning") is Severity.Warning


def test_default_config_ships_everything_to_cloud():
    cfg = Config.default()
    assert cfg.should_ship("any.tag", Severity.Verbose) is True
    assert cfg.should_ship("any.tag", Severity.Error) is True
    assert cfg.flush_severity is Severity.Warning
    assert cfg.max_time == 3.0


def test_should_ship_prefix_and_threshold():
    cfg = Config.from_dict(
        {
            "appenders": [{"type": "SBCloudAppender", "name": "cloud", "config": {}}],
            "loggers": [
                {"name": "", "severity": "Warning", "appenderRef": "cloud"},
                {"name": "myapp.db", "severity": "Verbose", "appenderRef": "cloud"},
            ],
        }
    )
    # Root logger only ships Warning-or-worse.
    assert cfg.should_ship("other", Severity.Warning) is True
    assert cfg.should_ship("other", Severity.Info) is False
    # The more specific prefix widens it to Verbose for that subtree.
    assert cfg.should_ship("myapp.db.pool", Severity.Debug) is True


def test_should_ship_ignores_non_cloud_loggers():
    cfg = Config.from_dict(
        {
            "appenders": [{"type": "ConsoleAppender", "name": "console", "config": {}}],
            "loggers": [{"name": "", "severity": "Verbose", "appenderRef": "console"}],
        }
    )
    # No cloud appender referenced → nothing ships.
    assert cfg.should_ship("x", Severity.Error) is False


def test_call_stack_severity():
    cfg = Config.from_dict(
        {
            "appenders": [{"type": "SBCloudAppender", "name": "cloud", "config": {}}],
            "loggers": [
                {
                    "name": "",
                    "severity": "Verbose",
                    "callStackSeverity": "Error",
                    "appenderRef": "cloud",
                }
            ],
        }
    )
    assert cfg.call_stack_severity("x") is Severity.Error


def test_config_reads_flush_knobs():
    cfg = Config.from_dict(
        {
            "appenders": [
                {
                    "type": "SBCloudAppender",
                    "name": "cloud",
                    "config": {"maxTime": 7, "flushSeverity": "Error", "flushSize": 12},
                }
            ],
            "loggers": [{"name": "", "severity": "Verbose", "appenderRef": "cloud"}],
            "configRefreshInterval": 120,
        }
    )
    assert cfg.max_time == 7.0
    assert cfg.flush_severity is Severity.Error
    assert cfg.flush_size == 12
    assert cfg.config_refresh_interval == 120
