from __future__ import annotations

import unittest
from datetime import timedelta

import requests

from anime_tracker.services.anilist.cancellation import CancellationToken
from anime_tracker.services.anilist.client import ANILIST_GRAPHQL_ENDPOINT
from anime_tracker.services.anilist.errors import AniListErrorType, AniListServiceError
from anime_tracker.services.anilist.queries import MEDIA_BY_ID_QUERY
from anime_tracker.services.anilist.rate_limit import MINIMUM_RETRY_DELAY, RetryPolicy, parse_retry_after, rate_limit_from_headers

from anilist_helpers import NOW, FakeResponse, client_for, fixture, media_response


class RateLimitParsingTests(unittest.TestCase):
    def test_remaining_count_and_reset_time(self):
        reset = int((NOW + timedelta(seconds=30)).timestamp())
        state = rate_limit_from_headers({"X-RateLimit-Limit": "90", "X-RateLimit-Remaining": "3", "X-RateLimit-Reset": str(reset)}, NOW)
        self.assertEqual((state.limit, state.remaining, state.reset_at), (90, 3, NOW + timedelta(seconds=30)))

    def test_retry_after_positive(self):
        self.assertEqual(parse_retry_after("7", NOW), 7.0)

    def test_retry_after_zero_has_safe_minimum(self):
        self.assertEqual(parse_retry_after("0", NOW), MINIMUM_RETRY_DELAY)

    def test_retry_after_missing(self):
        self.assertIsNone(parse_retry_after(None, NOW))

    def test_retry_after_invalid(self):
        self.assertIsNone(parse_retry_after("not-a-delay", NOW))

    def test_backoff_with_jitter_bounds(self):
        policy = RetryPolicy(base_delay_seconds=4, maximum_delay_seconds=30, jitter_ratio=0.25)
        self.assertEqual(policy.delay(1, random_value=0), 3.0)
        self.assertEqual(policy.delay(1, random_value=1), 5.0)
        self.assertLessEqual(policy.delay(10, random_value=1), 30.0)


class GraphQLClientTests(unittest.TestCase):
    def setUp(self):
        self.cases = fixture("media_cases.json")
        self.http = fixture("http_cases.json")

    def response_case(self, name):
        item = self.http[name]
        return FakeResponse(item["status"], item["body"], item["headers"])

    def test_request_uses_official_https_endpoint_and_timeouts(self):
        client, session = client_for([media_response(self.cases["upcoming_tv"])])
        client.execute(MEDIA_BY_ID_QUERY, {"id": 1001})
        url, kwargs = session.calls[0]
        self.assertEqual(url, ANILIST_GRAPHQL_ENDPOINT)
        self.assertEqual(kwargs["timeout"], (5.0, 20.0))
        self.assertEqual(set(kwargs["json"]), {"query", "variables"})

    def test_nonofficial_endpoint_is_rejected(self):
        from anime_tracker.services.anilist.client import AniListGraphQLClient
        with self.assertRaises(ValueError):
            AniListGraphQLClient(endpoint="https://example.test/graphql")

    def test_unknown_variables_local_paths_and_webhooks_are_rejected_before_network(self):
        client, session = client_for([media_response(self.cases["upcoming_tv"])])
        invalid = (
            {"secret": "value"},
            {"search": r"I:\Jellyfin_Media\Shows"},
            {"search": "https://discord.com/api/webhooks/123/private"},
        )
        for variables in invalid:
            with self.subTest(variables=variables), self.assertRaises(AniListServiceError) as error:
                client.execute(MEDIA_BY_ID_QUERY, variables)
            self.assertEqual(error.exception.error_type, AniListErrorType.INVALID_INPUT)
        self.assertEqual(session.calls, [])

    def test_rate_limit_retries_and_tracks_pause(self):
        sleeps = []
        client, session = client_for([self.response_case("rate_limited"), media_response(self.cases["upcoming_tv"])], retries=1, sleep=sleeps.append)
        result = client.execute(MEDIA_BY_ID_QUERY, {"id": 1001})
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleeps, [2.0])
        self.assertTrue(result.rate_limit_state.paused)

    def test_zero_retry_after_does_not_spin(self):
        sleeps = []
        client, session = client_for([self.response_case("rate_limited_zero"), media_response(self.cases["upcoming_tv"])], retries=1, sleep=sleeps.append)
        client.execute(MEDIA_BY_ID_QUERY, {"id": 1001})
        self.assertEqual(sleeps, [1.0])
        self.assertEqual(len(session.calls), 2)

    def test_maximum_retries_is_enforced(self):
        client, session = client_for([FakeResponse(503, {}), FakeResponse(503, {}), FakeResponse(503, {})], retries=2)
        with self.assertRaises(AniListServiceError) as error:
            client.execute(MEDIA_BY_ID_QUERY, {"id": 1001})
        self.assertEqual(error.exception.error_type, AniListErrorType.CONNECTION_ERROR)
        self.assertEqual(len(session.calls), 3)

    def test_permanent_graphql_error_is_not_retried(self):
        client, session = client_for([self.response_case("graphql_error"), media_response(self.cases["upcoming_tv"])], retries=3)
        with self.assertRaises(AniListServiceError) as error:
            client.execute(MEDIA_BY_ID_QUERY, {"id": 1001})
        self.assertEqual(error.exception.error_type, AniListErrorType.GRAPHQL_ERROR)
        self.assertEqual(len(session.calls), 1)

    def test_not_found_is_structured(self):
        client, _ = client_for([self.response_case("not_found")])
        with self.assertRaises(AniListServiceError) as error:
            client.execute(MEDIA_BY_ID_QUERY, {"id": 9999})
        self.assertEqual(error.exception.error_type, AniListErrorType.NOT_FOUND)
        self.assertFalse(error.exception.retryable)

    def test_timeout_and_connection_errors_are_structured(self):
        for exception, expected in ((requests.Timeout(), AniListErrorType.TIMEOUT), (requests.ConnectionError(), AniListErrorType.CONNECTION_ERROR)):
            with self.subTest(expected=expected):
                client, _ = client_for([exception])
                with self.assertRaises(AniListServiceError) as error:
                    client.execute(MEDIA_BY_ID_QUERY, {"id": 1})
                self.assertEqual(error.exception.error_type, expected)

    def test_malformed_json_and_shape_are_structured(self):
        for response in (FakeResponse(200, json_error=ValueError("bad")), self.response_case("malformed"), FakeResponse(200, {"wrong": {}})):
            with self.subTest(response=response.body):
                client, _ = client_for([response])
                with self.assertRaises(AniListServiceError) as error:
                    client.execute(MEDIA_BY_ID_QUERY, {"id": 1})
                self.assertEqual(error.exception.error_type, AniListErrorType.MALFORMED_RESPONSE)

    def test_cancellation_before_request(self):
        token = CancellationToken()
        token.cancel()
        client, session = client_for([media_response(self.cases["upcoming_tv"])])
        with self.assertRaises(AniListServiceError) as error:
            client.execute(MEDIA_BY_ID_QUERY, {"id": 1001}, token=token)
        self.assertEqual(error.exception.error_type, AniListErrorType.CANCELED)
        self.assertEqual(session.calls, [])

    def test_cancellation_during_backoff(self):
        token = CancellationToken()
        def canceling_response():
            token.cancel()
            return FakeResponse(503, {})
        client, session = client_for([canceling_response, media_response(self.cases["upcoming_tv"])], retries=2)
        with self.assertRaises(AniListServiceError) as error:
            client.execute(MEDIA_BY_ID_QUERY, {"id": 1001}, token=token)
        self.assertEqual(error.exception.error_type, AniListErrorType.CANCELED)
        self.assertEqual(len(session.calls), 1)

    def test_preflight_pacing_when_remaining_is_low(self):
        sleeps = []
        client, _ = client_for([media_response(self.cases["upcoming_tv"])], sleep=sleeps.append)
        client.rate_limit_state = rate_limit_from_headers({
            "X-RateLimit-Remaining": "1", "X-RateLimit-Reset": str(int((NOW + timedelta(seconds=5)).timestamp()))
        }, NOW)
        result = client.execute(MEDIA_BY_ID_QUERY, {"id": 1001})
        self.assertEqual(sleeps, [5.0])
        self.assertTrue(result.rate_limit_state.paused)


if __name__ == "__main__":
    unittest.main()
