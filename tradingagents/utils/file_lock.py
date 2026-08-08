"""Cross-platform advisory file lock (no fcntl — Windows-safe)."""

from __future__ import annotations

import os
import time
from pathlib import Path


class FileLock:
    """Advisory lock via O_CREAT|O_EXCL, with stale-lock recovery."""

    def __init__(self, target: Path, timeout: float = 10.0, stale_after: float = 60.0):
        self._path = Path(target).with_suffix(Path(target).suffix + ".lock")
        self._timeout = timeout
        self._stale_after = stale_after

    def __enter__(self):
        deadline = time.time() + self._timeout
        while True:
            try:
                fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode())
                finally:
                    os.close(fd)
                return self
            except FileExistsError:
                try:
                    age = time.time() - self._path.stat().st_mtime
                except OSError:
                    age = 0.0
                if age > self._stale_after:
                    self._path.unlink(missing_ok=True)
                    continue
                if time.time() > deadline:
                    raise TimeoutError(f"could not acquire {self._path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        self._path.unlink(missing_ok=True)


# Alias matching the plan's private name.
_FileLock = FileLock
