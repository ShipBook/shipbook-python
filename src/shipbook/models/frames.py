import os
import site
import sysconfig
from collections.abc import Iterable
from typing import Any

# The interpreter's own library folders: the standard library and where packages are installed.
_PATH_KEYS = ("stdlib", "platstdlib", "purelib", "platlib")
# Longest first: they nest (a venv's lib/pythonX.Y holds its site-packages), and the package
# name is read relative to the closest one.
_LIBRARY_DIRS = sorted(
    {
        os.path.join(os.path.abspath(path), "")
        for path in (
            *(sysconfig.get_paths().get(key) for key in _PATH_KEYS),
            *site.getsitepackages(),
            site.getusersitepackages(),
            # The SDK's own folder, also when it's installed in editable mode.
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        if path
    },
    key=len,
    reverse=True,
)

_in_app_include: tuple[str, ...] = ()


def set_in_app_include(packages: Iterable[str]) -> None:
    """Packages that are the app's own code although they're installed (e.g. ``pip install .``)."""
    global _in_app_include
    _in_app_include = tuple(packages)


def _in_app(filename: str) -> bool:
    # "<frozen importlib._bootstrap>", "<string>": the runtime's, not the app's.
    if filename.startswith("<"):
        return False
    path = os.path.abspath(filename)
    for library in _LIBRARY_DIRS:
        if path.startswith(library):
            relative = path[len(library) :]
            return relative.split(os.sep, 1)[0].removesuffix(".py") in _in_app_include
    return True


def to_frames(summaries: Iterable[Any]) -> list[dict[str, Any]]:
    """Wire frames, innermost first as the other SDKs send them, each marked ``inApp`` for the
    server, which groups a crash by its innermost frame of the app's own code."""
    return [
        {
            "methodName": frame.name,
            "fileName": frame.filename,
            "lineNumber": frame.lineno,
            "inApp": _in_app(frame.filename),
        }
        for frame in reversed(list(summaries))
    ]
