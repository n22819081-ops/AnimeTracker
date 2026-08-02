from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, repr=False)
class SecretValue:
    _value: str

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretValue([REDACTED])"

    def __str__(self) -> str:
        return "[REDACTED]"


class CredentialStore(Protocol):
    def store_secret(self, reference: str, value: str) -> None: ...
    def retrieve_secret(self, reference: str) -> SecretValue: ...
    def delete_secret(self, reference: str) -> None: ...
    def secret_exists(self, reference: str) -> bool: ...
    def list_references(self) -> tuple[str, ...]: ...


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def store_secret(self, reference: str, value: str) -> None:
        if not reference or not value:
            raise ValueError("Credential reference and secret are required.")
        self._values[reference] = value

    def retrieve_secret(self, reference: str) -> SecretValue:
        try:
            return SecretValue(self._values[reference])
        except KeyError as exc:
            raise KeyError(f"Credential reference not found: {reference}") from exc

    def delete_secret(self, reference: str) -> None:
        self._values.pop(reference, None)

    def secret_exists(self, reference: str) -> bool:
        return reference in self._values

    def list_references(self) -> tuple[str, ...]:
        return tuple(sorted(self._values))


def legacy_reference(channel: str, webhook_present: bool) -> tuple[str, bool]:
    return (f"anime-tracker/{channel.casefold()}/legacy-import-pending", bool(webhook_present))
