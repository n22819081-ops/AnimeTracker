from __future__ import annotations

import logging
import unittest
from dataclasses import replace
from unittest.mock import Mock

import requests

from anime_tracker.notifications_v2 import (
    ChannelPurpose, DeliveryResultType, DiscordDeliveryAdapter, EventType,
    InMemoryCredentialStore, SILENT_MESSAGE_FLAG, WindowsNotificationAdapter,
    discord_payload, render_event, render_restricted,
    run_optional_discord_check,
)
from anime_tracker.notifications_v2.credentials import legacy_reference
from anime_tracker.notifications_v2.legacy_adapter import adapt_legacy_notification_config
from anime_tracker.notifications_v2.privacy import PrivacyViolation, ensure_privacy_safe, redact_text, safe_error_summary
from anime_tracker.notifications_v2.templates import PRIVATE_DEFAULTS, SHARED_DEFAULTS, TemplateError, compact_messages

from notification_v2_helpers import event, message


class Response:
    def __init__(self,status,json_value=None):
        self.status_code=status
        self._json=json_value or {}
    def json(self):
        return self._json


class DiscordDeliveryTests(unittest.TestCase):
    def deliver_status(self,status):
        return DiscordDeliveryAdapter(post=Mock(return_value=Response(status))).deliver("https://test.invalid/hook",message())

    def test_success(self):
        self.assertEqual(self.deliver_status(204).result,DeliveryResultType.DELIVERED)

    def test_retryable_http_statuses(self):
        for status in (429,500,502,503,504):
            with self.subTest(status=status):
                self.assertEqual(self.deliver_status(status).result,DeliveryResultType.RETRYABLE_FAILURE)

    def test_permanent_http_statuses(self):
        for status in (400,401,403,404):
            with self.subTest(status=status):
                self.assertEqual(self.deliver_status(status).result,DeliveryResultType.PERMANENT_FAILURE)

    def test_timeout_and_connection_error_retry(self):
        for failure in (requests.Timeout("slow"),requests.ConnectionError("offline")):
            with self.subTest(failure=type(failure).__name__):
                result=DiscordDeliveryAdapter(post=Mock(side_effect=failure)).deliver("https://test.invalid/hook",message())
                self.assertTrue(result.retryable)

    def test_silent_flag_is_json_body_and_disabled_omits_it(self):
        post=Mock(return_value=Response(204))
        adapter=DiscordDeliveryAdapter(post=post)
        adapter.deliver("https://test.invalid/hook",message(ChannelPurpose.SHARED_ANNOUNCEMENT,silent=True))
        self.assertEqual(post.call_args.kwargs["json"]["flags"],SILENT_MESSAGE_FLAG)
        post.reset_mock()
        adapter.deliver("https://test.invalid/hook",message(ChannelPurpose.SHARED_ANNOUNCEMENT,silent=False))
        self.assertNotIn("flags",post.call_args.kwargs["json"])

    def test_every_split_message_keeps_silent_flag(self):
        post=Mock(return_value=Response(204))
        DiscordDeliveryAdapter(post=post).deliver("https://test.invalid/hook",message(ChannelPurpose.SHARED_ANNOUNCEMENT,silent=True,body="x"*7000))
        self.assertGreater(len(post.call_args_list),1)
        self.assertTrue(all(call.kwargs["json"]["flags"]==4096 for call in post.call_args_list))

    def test_allowed_mentions_are_disabled(self):
        self.assertEqual(discord_payload(message())["allowed_mentions"],{"parse":[]})

    def test_empty_webhook_is_permanent_without_http_call(self):
        post=Mock()
        result=DiscordDeliveryAdapter(post=post).deliver("",message())
        self.assertEqual(result.result,DeliveryResultType.PERMANENT_FAILURE)
        post.assert_not_called()

    def test_optional_integration_check_is_disabled_and_requires_explicit_webhook(self):
        adapter=Mock()
        self.assertEqual(run_optional_discord_check(enabled=False,adapter=adapter)["result"],"DISABLED")
        adapter.deliver.assert_not_called()
        with self.assertRaises(ValueError): run_optional_discord_check(enabled=True,adapter=adapter)

    def test_optional_integration_check_returns_redacted_result(self):
        adapter=Mock(); adapter.deliver.return_value=type("Result",(),{"result":DeliveryResultType.DELIVERED,"http_status":204,"error_type":""})()
        secret="https://test.invalid/dedicated-secret"
        result=run_optional_discord_check(enabled=True,dedicated_test_webhook=secret,adapter=adapter)
        self.assertTrue(result["successful"])
        self.assertNotIn(secret,repr(result))


class TemplateTests(unittest.TestCase):
    def test_private_templates_are_meaningful(self):
        cases=(
            (EventType.NEW_EPISODE_AIRED,"New Episode Aired"),
            (EventType.STARTED_AIRING,"Series Started Airing"),
            (EventType.SERIES_FINISHED_AIRING,"Series Finished Airing"),
            (EventType.MISSING_AIRED_EPISODES,"Missing Aired Episodes"),
            (EventType.COVERAGE_BECAME_COMPLETE,"Found on Jellyfin"),
            (EventType.SERVER_MAPPING_CHANGED,"Server Mapping Changed"),
            (EventType.REVIEW_REQUIRED,"Review Required"),
            (EventType.PROVIDER_REFRESH_PARTIAL_FAILURE,"AniList Refresh Partially Failed"),
            (EventType.WEEKLY_AIRING_SUMMARY,"Weekly Anime Tracker Summary"),
        )
        payload={"title":"Example Season 2","episode":4,"missing_episodes":[4],"mapping_label":"Season 02","summary":"One update"}
        for event_type,title in cases:
            with self.subTest(event_type=event_type):
                rendered=render_event(event(event_type.value,event_type=event_type,payload=payload),ChannelPurpose.PRIVATE_TRACKER)
                self.assertEqual(rendered.title,title)

    def test_shared_templates_are_simple_and_separate(self):
        cases=(
            (EventType.SHARED_EPISODES_AVAILABLE,"New Episodes Available",{"episodes":[4,5,6]}),
            (EventType.SHARED_SEASON_COMPLETE,"Season Complete",{}),
            (EventType.SHARED_SERIES_AVAILABLE,"New Anime Available",{}),
            (EventType.MOVIE_FOUND_ON_SERVER,"New Anime Movie Available",{}),
            (EventType.WEEKLY_SERVER_SUMMARY,"This Week on Jellyfin",{"summary":"New series"}),
        )
        for event_type,title,extra in cases:
            payload={"title":"Example Anime",**extra}
            rendered=render_event(event(event_type.value,event_type=event_type,payload=payload),ChannelPurpose.SHARED_ANNOUNCEMENT)
            self.assertEqual(rendered.title,title)
            self.assertEqual(rendered.fields,())

    def test_shared_channel_has_no_review_or_provider_template(self):
        for event_type in (EventType.REVIEW_REQUIRED,EventType.PROVIDER_REFRESH_PARTIAL_FAILURE,EventType.CONFIRMED_PATH_MISSING):
            with self.assertRaises(TemplateError):
                render_event(event(event_type.value,event_type=event_type),ChannelPurpose.SHARED_ANNOUNCEMENT)

    def test_default_filters_are_distinct(self):
        self.assertIn(EventType.REVIEW_REQUIRED,PRIVATE_DEFAULTS)
        self.assertNotIn(EventType.REVIEW_REQUIRED,SHARED_DEFAULTS)

    def test_restricted_renderer_rejects_missing_and_complex_placeholders(self):
        self.assertEqual(render_restricted("Hello {title}",{"title":"Anime"}),"Hello Anime")
        with self.assertRaises(TemplateError): render_restricted("{missing}",{})
        with self.assertRaises(TemplateError): render_restricted("{user.name}",{"user":"bad"})


class PrivacyCredentialWindowsTests(unittest.TestCase):
    def test_paths_webhooks_tokens_and_stack_are_redacted(self):
        raw="C:\\AnimeTracker\\data.db https://discord.com/api/webhooks/1/secret token=abc Traceback (most recent call last):\nsecret"
        cleaned=redact_text(raw)
        self.assertNotIn("secret",cleaned)
        self.assertNotIn("C:\\",cleaned)

    def test_unsafe_payload_is_rejected(self):
        with self.assertRaises(PrivacyViolation): ensure_privacy_safe({"body":r"I:\Jellyfin_Media\Anime\Show"})
        ensure_privacy_safe({"body":"Example Anime (2024), Season 02"})

    def test_safe_error_is_single_line_and_redacted(self):
        summary=safe_error_summary("failed C:\\AnimeTracker\\data.db\nTraceback secret")
        self.assertNotIn("C:\\",summary)
        self.assertNotIn("\n",summary)

    def test_credential_store_and_redacted_repr(self):
        store=InMemoryCredentialStore()
        secret="https://discord.com/api/webhooks/1/secret"
        store.store_secret("private",secret)
        value=store.retrieve_secret("private")
        self.assertEqual(value.reveal(),secret)
        self.assertNotIn(secret,repr(value))
        self.assertEqual(store.list_references(),("private",))
        store.delete_secret("private")
        self.assertFalse(store.secret_exists("private"))
        with self.assertRaises(KeyError): store.retrieve_secret("private")

    def test_legacy_config_adapter_never_returns_secret(self):
        secret="https://discord.com/api/webhooks/1/secret"
        adapted=adapt_legacy_notification_config({"discord_enabled":True,"discord_webhook_url":secret,"shared_silent":False})
        self.assertNotIn(secret,repr(adapted))
        self.assertTrue(adapted["private"]["secret_present"])

    def test_windows_enabled_disabled_and_failure_isolated(self):
        sent=[]
        enabled=WindowsNotificationAdapter(enabled=True,sender=lambda title,body: sent.append((title,body)))
        self.assertEqual(enabled.deliver(message()).result,DeliveryResultType.DELIVERED)
        self.assertEqual(len(sent),1)
        self.assertEqual(WindowsNotificationAdapter(enabled=False).deliver(message()).result,DeliveryResultType.CANCELED)
        failed=WindowsNotificationAdapter(enabled=True,sender=lambda *_: (_ for _ in ()).throw(RuntimeError("toast failed")))
        self.assertEqual(failed.deliver(message()).result,DeliveryResultType.PERMANENT_FAILURE)


if __name__ == "__main__": unittest.main()
