import os
import sysconfig
import traceback

from shipbook.models import frames
from shipbook.models.exception import stack_from_traceback

_SITE_PACKAGES = sysconfig.get_paths()["purelib"]


def _summary(filename, name="f", lineno=1):
    return traceback.FrameSummary(filename, lineno, name)


def test_frames_are_innermost_first_and_marked_in_app():
    def inner():
        raise ValueError("boom")

    def outer():
        inner()

    try:
        outer()
    except ValueError as error:
        stack = stack_from_traceback(error.__traceback__)

    assert [frame["methodName"] for frame in stack] == [
        "inner",
        "outer",
        "test_frames_are_innermost_first_and_marked_in_app",
    ]
    assert all(frame["inApp"] for frame in stack)


def test_installed_packages_the_standard_library_and_the_runtime_are_not_the_apps():
    stdlib = os.path.join(sysconfig.get_paths()["stdlib"], "json", "decoder.py")
    library = os.path.join(_SITE_PACKAGES, "requests", "api.py")
    stack = frames.to_frames(
        [
            _summary("<frozen importlib._bootstrap>"),
            _summary(stdlib),
            _summary(library),
            _summary("/srv/app/views.py"),
        ]
    )
    assert [frame["inApp"] for frame in stack] == [True, False, False, False]


def test_an_app_installed_as_a_package_is_named_in_app():
    frames.set_in_app_include(["myapp"])
    try:
        stack = frames.to_frames(
            [
                _summary(os.path.join(_SITE_PACKAGES, "requests", "api.py")),
                _summary(os.path.join(_SITE_PACKAGES, "myapp", "orders", "views.py")),
                _summary(os.path.join(_SITE_PACKAGES, "myapp.py")),
            ]
        )
    finally:
        frames.set_in_app_include(())
    assert [frame["inApp"] for frame in stack] == [True, True, False]
