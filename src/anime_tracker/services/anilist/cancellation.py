from __future__ import annotations

from threading import Event
from typing import Protocol


class Cancellation(Protocol):
    """Shared interruptible-cancellation contract for background operations."""

    def is_cancelled(self) -> bool: ...
    def cancel(self) -> None: ...
    def wait(self, timeout: float) -> bool: ...


class CancellationToken:
    def __init__(self, event: Event | None = None) -> None:
        self._event = event or Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def is_canceled(self) -> bool:
        """Compatibility spelling retained for existing service callers."""
        return self.is_cancelled()

    def wait(self, timeout: float) -> bool:
        """Return true if cancellation occurs while waiting."""
        return self._event.wait(max(0.0, timeout))

    # Event-compatible aliases keep existing worker callables source-compatible.
    def is_set(self) -> bool:
        return self.is_cancelled()

    def set(self) -> None:
        self.cancel()
