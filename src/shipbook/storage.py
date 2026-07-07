import json
import os
import tempfile
import threading
from typing import Any, Optional


class Storage:
    """Filesystem-backed key/value + append-only JSONL queues, mirroring the
    node SDK's storage adapter so queued logs survive a process restart.

    Queue files are per-pid so concurrent workers (e.g. gunicorn) never contend
    on the same file; each worker uploads its own buffered logs.
    """

    def __init__(self, directory: Optional[str] = None) -> None:
        self._dir = directory or os.environ.get("SHIPBOOK_STORAGE_PATH") or os.path.join(
            tempfile.gettempdir(), ".shipbook"
        )
        self._lock = threading.RLock()
        self._enabled = True
        try:
            os.makedirs(self._dir, exist_ok=True)
        except OSError:
            # No writable disk — fall back to in-memory only.
            self._enabled = False
        self._mem_items: dict = {}
        self._mem_queues: dict = {}

    def _path(self, name: str) -> str:
        return os.path.join(self._dir, name)

    def _queue_path(self, key: str) -> str:
        return self._path(f"{key}.{os.getpid()}.jsonl")

    def get_item(self, key: str) -> Optional[str]:
        with self._lock:
            if not self._enabled:
                return self._mem_items.get(key)
            try:
                with open(self._path(key), encoding="utf-8") as f:
                    return f.read()
            except FileNotFoundError:
                return None

    def set_item(self, key: str, value: str) -> None:
        with self._lock:
            if not self._enabled:
                self._mem_items[key] = value
                return
            with open(self._path(key), "w", encoding="utf-8") as f:
                f.write(value)

    def get_obj(self, key: str) -> Optional[Any]:
        raw = self.get_item(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_obj(self, key: str, value: Any) -> None:
        self.set_item(key, json.dumps(value))

    def push_array_obj(self, key: str, obj: Any) -> None:
        line = json.dumps(obj)
        with self._lock:
            if not self._enabled:
                self._mem_queues.setdefault(key, []).append(obj)
                return
            with open(self._queue_path(key), "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def pop_all_array_obj(self, key: str) -> list[Any]:
        """Atomically drain the queue: rename it aside, read, delete. Pushes
        that arrive after the rename land in a fresh queue file."""
        with self._lock:
            if not self._enabled:
                items = self._mem_queues.pop(key, [])
                return items

            path = self._queue_path(key)
            tmp = path + ".tmp"
            try:
                os.replace(path, tmp)
            except FileNotFoundError:
                return []

            out: list[Any] = []
            with open(tmp, encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        out.append(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
            os.remove(tmp)
            return out
