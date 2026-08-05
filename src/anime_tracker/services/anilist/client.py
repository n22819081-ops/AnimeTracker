from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

import requests

from .cancellation import Cancellation
from .errors import AniListErrorType, AniListServiceError
from .models import RateLimitState
from .rate_limit import RetryPolicy, cancellable_wait, rate_limit_from_headers

LOGGER = logging.getLogger(__name__)
ANILIST_GRAPHQL_ENDPOINT = "https://graphql.anilist.co"
ALLOWED_VARIABLES = {"id", "malId", "search", "page", "perPage", "year", "format", "season", "ids", "from", "to"}


def validate_graphql_variables(variables: Mapping[str, Any]) -> None:
    if not set(variables).issubset(ALLOWED_VARIABLES):
        raise AniListServiceError(AniListErrorType.INVALID_INPUT, "AniList request contains unsupported variables.")
    values = []
    for value in variables.values():
        values.extend(value if isinstance(value, (list, tuple)) else (value,))
    for value in values:
        if not isinstance(value, str):
            continue
        lowered = value.casefold()
        if re.match(r"^[a-z]:[\\/]", value, re.IGNORECASE) or value.startswith("\\\\"):
            raise AniListServiceError(AniListErrorType.INVALID_INPUT, "Local paths cannot be sent to AniList.")
        if "discord.com/api/webhooks" in lowered or "discordapp.com/api/webhooks" in lowered:
            raise AniListServiceError(AniListErrorType.INVALID_INPUT, "Webhook values cannot be sent to AniList.")


@dataclass(frozen=True)
class GraphQLResult:
    data: Mapping[str, Any]
    rate_limit_state: RateLimitState
    network_requests: int
    rate_limit_pauses: int


class AniListGraphQLClient:
    def __init__(
        self,
        *,
        session: Any | None = None,
        endpoint: str = ANILIST_GRAPHQL_ENDPOINT,
        connect_timeout: float = 5.0,
        read_timeout: float = 20.0,
        retry_policy: RetryPolicy = RetryPolicy(),
        sleep=time.sleep,
        clock=lambda: datetime.now(timezone.utc),
        random_value=lambda: 0.5,
    ) -> None:
        if endpoint != ANILIST_GRAPHQL_ENDPOINT or not endpoint.startswith("https://"):
            raise ValueError("The modern AniList client only permits the official HTTPS GraphQL endpoint.")
        self.session = session or requests.Session()
        self.endpoint = endpoint
        self.timeout = (connect_timeout, read_timeout)
        self.retry_policy = retry_policy
        self.sleep = sleep
        self.clock = clock
        self.random_value = random_value
        self.rate_limit_state = RateLimitState()
        self.last_network_requests = 0
        self.last_rate_limit_pauses = 0

    def _preflight_pause(self, token: Cancellation | None) -> bool:
        state = self.rate_limit_state
        now = self.clock()
        if state.remaining is not None and state.remaining <= 1 and state.reset_at and state.reset_at > now:
            seconds = max(1.0, (state.reset_at - now).total_seconds())
            if cancellable_wait(seconds, token, self.sleep):
                raise AniListServiceError(AniListErrorType.CANCELED, "AniList operation was canceled.")
            return True
        return False

    def execute(
        self,
        query: str,
        variables: Mapping[str, Any],
        *,
        token: Cancellation | None = None,
    ) -> GraphQLResult:
        validate_graphql_variables(variables)
        if token and token.is_cancelled():
            raise AniListServiceError(AniListErrorType.CANCELED, "AniList operation was canceled.")
        requests_made = 0
        pauses = 1 if self._preflight_pause(token) else 0
        self.last_network_requests = 0
        self.last_rate_limit_pauses = pauses
        last_error: AniListServiceError | None = None
        for attempt in range(1, self.retry_policy.maximum_retries + 2):
            if token and token.is_cancelled():
                raise AniListServiceError(AniListErrorType.CANCELED, "AniList operation was canceled.")
            try:
                requests_made += 1
                self.last_network_requests = requests_made
                response = self.session.post(
                    self.endpoint,
                    json={"query": query, "variables": dict(variables)},
                    timeout=self.timeout,
                )
            except requests.Timeout:
                error = AniListServiceError(AniListErrorType.TIMEOUT, "AniList request timed out.", True)
            except requests.ConnectionError:
                error = AniListServiceError(AniListErrorType.CONNECTION_ERROR, "AniList could not be reached.", True)
            except requests.RequestException:
                error = AniListServiceError(AniListErrorType.CONNECTION_ERROR, "AniList request could not be completed.", True)
            else:
                self.rate_limit_state = rate_limit_from_headers(response.headers, self.clock())
                error = self._response_error(response)
                if error is None:
                    try:
                        payload = response.json()
                    except (TypeError, ValueError):
                        error = AniListServiceError(AniListErrorType.MALFORMED_RESPONSE, "AniList returned malformed JSON.", True, response.status_code)
                    else:
                        if not isinstance(payload, Mapping):
                            error = AniListServiceError(AniListErrorType.MALFORMED_RESPONSE, "AniList returned an invalid response object.", True, response.status_code)
                        elif payload.get("errors"):
                            error = self._graphql_error(payload["errors"], response.status_code)
                        elif not isinstance(payload.get("data"), Mapping):
                            error = AniListServiceError(AniListErrorType.MALFORMED_RESPONSE, "AniList response did not contain data.", True, response.status_code)
                        else:
                            self.last_rate_limit_pauses = pauses
                            state = replace(self.rate_limit_state, paused=pauses > 0 or self.rate_limit_state.paused)
                            return GraphQLResult(payload["data"], state, requests_made, pauses)
            last_error = error
            LOGGER.warning("AniList request attempt %s failed with %s.", attempt, error.error_type.value)
            if not error.retryable or attempt > self.retry_policy.maximum_retries:
                break
            delay = self.retry_policy.delay(attempt, error.retry_after_seconds, self.random_value())
            pauses += 1
            self.last_rate_limit_pauses = pauses
            if cancellable_wait(delay, token, self.sleep):
                raise AniListServiceError(AniListErrorType.CANCELED, "AniList operation was canceled.")
        assert last_error is not None
        self.last_rate_limit_pauses = pauses
        raise last_error

    def _response_error(self, response: Any) -> AniListServiceError | None:
        status = int(response.status_code)
        if status == 429:
            return AniListServiceError(
                AniListErrorType.RATE_LIMITED,
                "AniList rate limit was reached.",
                True,
                status,
                self.rate_limit_state.retry_after_seconds,
            )
        if status == 404:
            return AniListServiceError(AniListErrorType.NOT_FOUND, "AniList media was not found.", False, status)
        if 500 <= status <= 599:
            return AniListServiceError(AniListErrorType.CONNECTION_ERROR, "AniList is temporarily unavailable.", True, status)
        if status < 200 or status >= 300:
            return AniListServiceError(AniListErrorType.GRAPHQL_ERROR, "AniList rejected the request.", False, status)
        return None

    @staticmethod
    def _graphql_error(errors: Any, status: int) -> AniListServiceError:
        entries = errors if isinstance(errors, list) else []
        messages = [str(item.get("message") or "") for item in entries if isinstance(item, Mapping)]
        safe = " ".join(messages).casefold()
        if "not found" in safe:
            return AniListServiceError(AniListErrorType.NOT_FOUND, "AniList media was not found.", False, status)
        retryable = any("internal" in message.casefold() or "temporar" in message.casefold() for message in messages)
        return AniListServiceError(AniListErrorType.GRAPHQL_ERROR, "AniList returned a GraphQL error.", retryable, status)
