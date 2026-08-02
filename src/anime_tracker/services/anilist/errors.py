from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AniListErrorType(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    GRAPHQL_ERROR = "GRAPHQL_ERROR"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    CANCELED = "CANCELED"
    OFFLINE_CACHE_USED = "OFFLINE_CACHE_USED"
    PARTIAL_BATCH_FAILURE = "PARTIAL_BATCH_FAILURE"
    CACHE_CORRUPT = "CACHE_CORRUPT"


@dataclass(frozen=True)
class AniListServiceError(Exception):
    error_type: AniListErrorType
    safe_message: str
    retryable: bool = False
    http_status: int | None = None
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        return self.safe_message
