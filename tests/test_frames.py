import json.decoder
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


def test_the_standard_library_as_python_imports_it_is_not_the_apps():
    # Not the path sysconfig names: under Homebrew that one goes through a symlink.
    assert not frames.in_app(json.decoder.__file__)
    assert not frames.in_app(traceback.__file__)


def test_a_library_folder_named_through_a_symlink_is_not_the_apps(tmp_path, monkeypatch):
    (tmp_path / "Cellar" / "lib" / "json").mkdir(parents=True)
    (tmp_path / "opt").symlink_to(tmp_path / "Cellar", target_is_directory=True)
    monkeypatch.setattr(
        frames, "_LIBRARY_DIRS", frames._library_dirs([str(tmp_path / "opt" / "lib")])
    )
    frames.in_app.cache_clear()

    assert not frames.in_app(str(tmp_path / "Cellar" / "lib" / "json" / "decoder.py"))
    assert not frames.in_app(str(tmp_path / "opt" / "lib" / "json" / "decoder.py"))
    assert frames.in_app(str(tmp_path / "app" / "views.py"))


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
