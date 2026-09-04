from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from anime_tracker.anilist import ANILIST_URL, HEALTH_CHECK_QUERY, AniListClient


def make_client(post_side_effect) -> tuple[AniListClient, MagicMock]:
    """Build an AniListClient whose session.post is mocked."""
    client = AniListClient()
    fake_session = MagicMock()
    fake_session.post.side_effect = post_side_effect
    client.session = fake_session
    return client, fake_session


def make_response(status: int = 200, body: object = None, content: bytes | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    if content is not None:
        response.content = content
        if body is not None:
            response.json.return_value = body
        else:
            response.json.side_effect = ValueError("not json")
    elif body is not None:
        response.json.return_value = body
    else:
        response.json.return_value = {"data": {"Media": {"id": 1, "title": {"romaji": "Cowboy Bebop"}}}}
    return response


class HealthCheckSuccessTests(unittest.TestCase):
    def test_usable_response_is_online(self):
        client, session = make_client(
            lambda *a, **kw: make_response(200, {"data": {"Media": {"id": 1, "title": {"romaji": "Cowboy Bebop"}}}})
        )
        online, detail = client.health_check()
        self.assertTrue(online)
        self.assertIn("health check", detail)

    def test_request_uses_public_endpoint_and_health_query_without_credentials(self):
        client, session = make_client(lambda *a, **kw: make_response(200))
        client.health_check(timeout=3.5)
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], ANILIST_URL)
        self.assertEqual(kwargs["timeout"], 3.5)
        payload = kwargs["json"]
        self.assertEqual(set(payload), {"query", "variables"})
        self.assertEqual(payload["query"], HEALTH_CHECK_QUERY)
        self.assertEqual(payload["variables"], {})
        # No auth headers or credentials are sent.
        self.assertNotIn("headers", kwargs)
        self.assertNotIn("auth", kwargs)

    def test_sends_exactly_one_request_no_retries(self):
        client, session = make_client(lambda *a, **kw: make_response(200))
        client.health_check()
        self.assertEqual(session.post.call_count, 1)


class HealthCheckFailureTests(unittest.TestCase):
    def test_429_rate_limit_is_not_success(self):
        response = make_response(429)
        response.headers = {"Retry-After": "60"}
        client, _ = make_client(lambda *a, **kw: response)
        online, detail = client.health_check()
        self.assertFalse(online)
        self.assertIn("429", detail)

    def test_http_error_status_is_offline(self):
        client, _ = make_client(lambda *a, **kw: make_response(500))
        online, detail = client.health_check()
        self.assertFalse(online)
        self.assertIn("500", detail)

    def test_network_error_is_offline(self):
        client, _ = make_client(lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("connection refused")))
        online, detail = client.health_check()
        self.assertFalse(online)
        self.assertIn("ConnectionError", detail)

    def test_timeout_is_offline(self):
        client, _ = make_client(lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout("timed out")))
        online, detail = client.health_check()
        self.assertFalse(online)
        self.assertIn("Timeout", detail)

    def test_non_json_body_is_offline(self):
        client, _ = make_client(lambda *a, **kw: make_response(200, content=b"<html>nope</html>"))
        online, detail = client.health_check()
        self.assertFalse(online)
        self.assertIn("non-JSON", detail)

    def test_graphql_errors_are_offline(self):
        client, _ = make_client(
            lambda *a, **kw: make_response(200, {"errors": [{"message": "boom"}], "data": None})
        )
        online, detail = client.health_check()
        self.assertFalse(online)
        self.assertIn("error", detail)

    def test_missing_media_data_is_offline(self):
        client, _ = make_client(lambda *a, **kw: make_response(200, {"data": {}}))
        online, detail = client.health_check()
        self.assertFalse(online)
        self.assertIn("unusable", detail)

    def test_non_dict_payload_is_offline(self):
        client, _ = make_client(lambda *a, **kw: make_response(200, ["unexpected", "list"]))
        online, detail = client.health_check()
        self.assertFalse(online)
        self.assertIn("error", detail)


class HealthCheckNoSideEffectsTests(unittest.TestCase):
    def test_health_check_does_not_sleep_on_rate_limit(self):
        response = make_response(429)
        response.headers = {"Retry-After": "99"}
        client, _ = make_client(lambda *a, **kw: response)
        with patch("anime_tracker.anilist.time.sleep") as sleep:
            online, _ = client.health_check()
        self.assertFalse(online)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
