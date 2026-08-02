from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


class OperationAlreadyRunning(RuntimeError): pass


class FileOperationLock:
    def __init__(self, path: Path, *, stale_after: timedelta = timedelta(hours=8)) -> None:
        self.path = Path(path); self.stale_after = stale_after; self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self._stale(): self.path.unlink(missing_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise OperationAlreadyRunning(f"Operation lock is already held: {self.path.name}") from exc
        payload = json.dumps({"pid": os.getpid(), "created_at": datetime.now(timezone.utc).isoformat()}).encode("utf-8")
        try: os.write(descriptor, payload)
        finally: os.close(descriptor)
        self.acquired = True

    def _stale(self) -> bool:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")); created = datetime.fromisoformat(value["created_at"])
            return datetime.now(timezone.utc) - created > self.stale_after
        except (OSError, ValueError, KeyError, TypeError): return False

    def release(self) -> None:
        if self.acquired: self.path.unlink(missing_ok=True); self.acquired = False

    def __enter__(self): self.acquire(); return self
    def __exit__(self, *_): self.release()
