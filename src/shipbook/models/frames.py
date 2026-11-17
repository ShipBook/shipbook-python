import functools
import os
import site
import sysconfig
from collections.abc import Iterable
from typing import Any, Optional

# The interpreter's own library folders: the standard library and where packages are installed.
_PATH_KEYS = ("stdlib", "platstdlib", "purelib", "platlib")


def _library_dirs(paths: Iterable[Optional[str]]) -> list[str]:
    """Each folder as given and with its symlinks resolved: Homebrew names its standard library
    through one, while a frame's file is the resolved path. Longest first, because they nest
    (a venv's lib/pythonX.Y holds its site-packages) and a package is named by the closest."""
    forms = (os.path.abspath, os.path.realpath)
    dirs = {os.path.join(form(path), "") for path in paths if path for form in forms}
    return sorted(dirs, key=len, reverse=True)


_LIBRARY_DIRS = _library_dirs(
    (
        *(sysconfig.get_paths().get(key) for key in _PATH_KEYS),
        *site.getsitepackages(),
        site.getusersitepackages(),
        # The SDK's own folder, also when it's installed in editable mode.
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
)

_in_app_include: tuple[str, ...] = ()


def set_in_app_include(packages: Iterable[str]) -> None:
    """Packages that are the app's own code although they're installed (e.g. ``pip install .``)."""
    global _in_app_include
    _in_app_include = tuple(packages)
    in_app.cache_clear()


# Cached: resolving a path asks the file system, and the same files come up in every stack.
@functools.lru_cache(maxsize=2048)
def in_app(filename: str) -> bool:
    """Whether a frame's file is the app's own code, not the runtime's or an installed package's."""
    # "<frozen importlib._bootstrap>", "<string>": the runtime's, not the app's.
    if filename.startswith("<"):
        return False
    for path in (os.path.abspath(filename), os.path.realpath(filename)):
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
            "inApp": in_app(frame.filename),
        }
        for frame in reversed(list(summaries))
    ]
