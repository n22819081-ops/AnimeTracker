from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..services.anilist.cancellation import CancellationToken


@dataclass(frozen=True)
class WorkerProgress:
    worker_id: str
    current: int
    total: int
    message: str


class WorkerSignals(QObject):
    started = Signal(str)
    progress = Signal(object)
    result = Signal(object)
    partial = Signal(object)
    error = Signal(str, str)
    canceled = Signal(str)
    finished = Signal(str)


class BackgroundWorker(QRunnable):
    def __init__(self, operation: Callable, *args, worker_id: str | None = None, **kwargs) -> None:
        super().__init__()
        self.operation = operation
        self.args = args
        self.kwargs = kwargs
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex}"
        self.cancel_token = CancellationToken()
        self.cancel_event = self.cancel_token
        self.signals = WorkerSignals()
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def report(self, current: int, total: int, message: str = "") -> None:
        self.signals.progress.emit(WorkerProgress(self.worker_id, current, total, message))

    @Slot()
    def run(self) -> None:
        self.signals.started.emit(self.worker_id)
        try:
            result = self.operation(*self.args, cancel_event=self.cancel_event, progress=self.report, **self.kwargs)
            if self.cancel_token.is_cancelled():
                self.signals.canceled.emit(self.worker_id)
            else:
                self.signals.result.emit(result)
        except Exception as exc:
            details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.signals.error.emit(type(exc).__name__, details)
        finally:
            self.signals.finished.emit(self.worker_id)
