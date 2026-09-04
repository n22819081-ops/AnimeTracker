from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from anime_tracker.modernization.schema_v4 import (
    initialize_matching_test_database,
    migrate_modern_database_to_v4,
)
from anime_tracker.services.matching import (
    MatchingRejectionScope,
    MatchingRepository,
    MatchingService,
    StaleCandidateError,
)

from matching_helpers import NOW, inventory_item, media, snapshot


ROOT = Path(__file__).resolve().parents[1]
V3_PROTOTYPE = ROOT / "Modern Anime Tracker" / "migration_test" / "anime_tracker_modern_v3.db"
LIVE_DB = ROOT / "Legacy Anime Tracker" / "data" / "anime_tracker.db"
LIVE_HASH = "0CBA84F7D08EAD16A69C1DF49D0A79A8351940A4D28E8049C60E591A1176BEB8"


class SchemaV4Tests(unittest.TestCase):
    @unittest.skipUnless(V3_PROTOTYPE.exists(), "schema-v3 prototype is unavailable")
    def test_v3_copy_migrates_to_v4_with_history_and_no_row_loss(self):
        source_hash = hashlib.sha256(V3_PROTOTYPE.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "modern-v4.db"
            shutil.copy2(V3_PROTOTYPE, copy)
            migrate_modern_database_to_v4(copy, live_database_path=LIVE_DB, protected_roots=())
            connection = sqlite3.connect(copy)
            try:
                versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
                self.assertEqual(versions, [1, 2, 3, 4])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM media_server_mappings").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM rejected_match_decisions").fetchone()[0], 11)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM server_match_candidates").fetchone()[0], 14)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM review_cases").fetchone()[0], 5)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM legacy_review_cases_v1").fetchone()[0], 64)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM archived_legacy_records").fetchone()[0], 421)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                connection.close()
        self.assertEqual(hashlib.sha256(V3_PROTOTYPE.read_bytes()).hexdigest(), source_hash)

    @unittest.skipUnless(V3_PROTOTYPE.exists(), "schema-v3 prototype is unavailable")
    def test_v4_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "modern-v4.db"
            shutil.copy2(V3_PROTOTYPE, copy)
            migrate_modern_database_to_v4(copy, protected_roots=())
            migrate_modern_database_to_v4(copy, protected_roots=())
            connection = sqlite3.connect(copy)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=4").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM media_server_mappings").fetchone()[0], 1)
            finally:
                connection.close()

    @unittest.skipUnless(V3_PROTOTYPE.exists(), "schema-v3 prototype is unavailable")
    def test_v4_migration_rolls_back_renames_and_rows_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "modern-v4.db"
            shutil.copy2(V3_PROTOTYPE, copy)
            with patch("anime_tracker.modernization.schema_v4._copy_legacy_rows", side_effect=RuntimeError("forced")):
                with self.assertRaises(RuntimeError):
                    migrate_modern_database_to_v4(copy, protected_roots=())
            connection = sqlite3.connect(copy)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=4").fetchone()[0], 0)
                self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_candidates'").fetchone())
                self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_match_candidates_v1'").fetchone())
            finally:
                connection.close()

    def test_live_database_migration_is_refused(self):
        with self.assertRaises(ValueError):
            migrate_modern_database_to_v4(LIVE_DB, live_database_path=LIVE_DB, protected_roots=())
        self.assertEqual(hashlib.sha256(LIVE_DB.read_bytes()).hexdigest().upper(), LIVE_HASH)


class MatchingPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "matching.db"
        initialize_matching_test_database(self.db)
        self.repo = MatchingRepository(self.db)
        self.service = MatchingService(self.repo, clock=lambda: NOW)
        self.media = media()
        self.inventory = snapshot(inventory_item())

    def tearDown(self):
        self.temp.cleanup()

    def generate(self, *, session_id="session-1", profile_id="default", media_value=None, inventory=None):
        return self.service.generate_candidates(
            media_value or self.media,
            inventory or self.inventory,
            session_id=session_id,
            profile_id=profile_id,
        )

    def confirm(self, *, profile_id="default"):
        generated = self.generate(profile_id=profile_id)
        return self.service.confirm_mapping(
            generated.candidates[0].candidate_id, self.media, self.inventory, profile_id=profile_id,
        )

    def test_mapping_persists_across_repository_restart(self):
        mapping = self.confirm()
        restarted = MatchingRepository(self.db)
        self.assertEqual(restarted.list_mappings("default", self.media.anilist_id)[0].mapping_id, mapping.mapping_id)

    def test_rejection_persists_across_restart_and_inventory_reorder(self):
        second_item = inventory_item("Example Anime Alternate (2024)", item_id="other")
        inventory = snapshot(inventory_item(), second_item)
        generated = self.service.generate_candidates(self.media, inventory, session_id="before")
        target = generated.candidates[0]
        self.service.reject_candidate(target.candidate_id, MatchingRejectionScope.EXACT_TARGET)
        restarted = MatchingService(MatchingRepository(self.db), clock=lambda: NOW)
        after = restarted.generate_candidates(self.media, snapshot(inventory_item(), second_item, reverse=True), session_id="after")
        matching = next(item for item in after.candidates if item.target.identity_key == target.target.identity_key)
        self.assertEqual(matching.confidence.value, "REJECTED")

    def test_case_normalized_folder_rejection_persists(self):
        generated = self.generate()
        rejection = self.service.reject_candidate(generated.candidates[0].candidate_id, MatchingRejectionScope.FOLDER)
        connection = sqlite3.connect(self.db)
        connection.execute("UPDATE rejected_match_decisions SET target_identity=upper(target_identity) WHERE rejection_id=?", (rejection.rejection_id,))
        connection.commit()
        connection.close()
        regenerated = self.generate(session_id="session-2")
        self.assertEqual(regenerated.candidates[0].confidence.value, "REJECTED")

    def test_clear_rejection_allows_candidate_again(self):
        candidate = self.generate().candidates[0]
        rejection = self.service.reject_candidate(candidate.candidate_id, MatchingRejectionScope.CANDIDATE)
        self.assertEqual(self.generate(session_id="rejected").candidates[0].confidence.value, "REJECTED")
        self.service.clear_rejection(rejection.rejection_id)
        self.assertNotEqual(self.generate(session_id="cleared").candidates[0].confidence.value, "REJECTED")

    def test_stable_item_rejection_persists(self):
        candidate = self.generate().candidates[0]
        self.service.reject_candidate(candidate.candidate_id, MatchingRejectionScope.STABLE_INVENTORY_ITEM)
        regenerated = self.generate(session_id="stable-rejected")
        self.assertEqual(regenerated.candidates[0].confidence.value, "REJECTED")

    def test_changed_stable_item_identity_creates_review_instead_of_broad_rejection(self):
        candidate = self.generate().candidates[0]
        self.service.reject_candidate(candidate.candidate_id, MatchingRejectionScope.STABLE_INVENTORY_ITEM)
        changed = snapshot(inventory_item(item_id="replacement-stable-id"))
        result = self.generate(session_id="changed-identity", inventory=changed)
        self.assertNotEqual(result.candidates[0].confidence.value, "REJECTED")
        self.assertTrue(any("changed stable inventory identity" in warning for warning in result.candidates[0].evidence.warnings))
        self.assertTrue(any(
            review.review_type.value == "UNSTABLE_REJECTED_TARGET"
            for review in self.repo.list_reviews("default", anilist_id=self.media.anilist_id)
        ))

    def test_expired_rejection_is_reconsidered(self):
        candidate = self.generate().candidates[0]
        self.service.reject_candidate(
            candidate.candidate_id,
            MatchingRejectionScope.EXACT_TARGET,
            expires_at=NOW.replace(year=2025),
        )
        regenerated = self.generate(session_id="expired")
        self.assertNotEqual(regenerated.candidates[0].confidence.value, "REJECTED")

    def test_explicit_franchise_rejection_requires_and_uses_identity(self):
        candidate = self.generate().candidates[0]
        with self.assertRaises(ValueError):
            self.service.reject_candidate(candidate.candidate_id, MatchingRejectionScope.FRANCHISE)
        self.service.reject_candidate(
            candidate.candidate_id, MatchingRejectionScope.FRANCHISE, franchise_identity="franchise-1",
        )
        regenerated = self.service.generate_candidates(
            self.media, self.inventory, session_id="franchise", franchise_identity="franchise-1",
        )
        self.assertEqual(regenerated.candidates[0].confidence.value, "REJECTED")

    def test_suppression_persists_and_clear_restores_generation(self):
        self.service.suppress_auto_match(self.media.anilist_id, reason="later")
        restarted = MatchingService(MatchingRepository(self.db), clock=lambda: NOW)
        self.assertTrue(restarted.generate_candidates(self.media, self.inventory, session_id="suppressed").suppressed)
        restarted.restore_auto_match(self.media.anilist_id)
        self.assertTrue(restarted.generate_candidates(self.media, self.inventory, session_id="restored").candidates)

    def test_profiles_do_not_share_rejections_suppressions_or_mappings(self):
        generated = self.generate(profile_id="one")
        self.service.reject_candidate(generated.candidates[0].candidate_id, MatchingRejectionScope.EXACT_TARGET, profile_id="one")
        self.service.suppress_auto_match(self.media.anilist_id, profile_id="one")
        profile_two = self.generate(session_id="profile-two", profile_id="two")
        self.assertFalse(profile_two.suppressed)
        self.assertNotEqual(profile_two.candidates[0].confidence.value, "REJECTED")
        self.assertEqual(self.repo.list_mappings("two", self.media.anilist_id), ())

    def test_inventory_change_makes_candidate_stale(self):
        generated = self.generate()
        changed = snapshot(inventory_item(seasons={1: range(1, 11)}))
        with self.assertRaises(StaleCandidateError):
            self.service.confirm_mapping(generated.candidates[0].candidate_id, self.media, changed)

    def test_anilist_metadata_change_makes_candidate_stale(self):
        generated = self.generate()
        changed = replace(self.media, provider_updated_at=2)
        with self.assertRaises(StaleCandidateError):
            self.service.confirm_mapping(generated.candidates[0].candidate_id, changed, self.inventory)

    def test_regeneration_after_change_restores_confirmable_candidate(self):
        changed = replace(self.media, provider_updated_at=2)
        generated = self.service.generate_candidates(changed, self.inventory, session_id="fresh")
        mapping = self.service.confirm_mapping(generated.candidates[0].candidate_id, changed, self.inventory)
        self.assertTrue(mapping.is_confirmed)

    def test_confirmation_supersedes_old_mapping_and_preserves_history(self):
        first = self.confirm()
        other_inventory = snapshot(inventory_item("Example Anime Alternate (2024)", item_id="other"))
        generated = self.service.generate_candidates(self.media, other_inventory, session_id="replacement")
        second = self.service.confirm_mapping(generated.candidates[0].candidate_id, self.media, other_inventory)
        mappings = self.repo.list_mappings("default", self.media.anilist_id, include_inactive=True)
        self.assertEqual(len(mappings), 2)
        self.assertFalse(next(item for item in mappings if item.mapping_id == first.mapping_id).active)
        self.assertTrue(next(item for item in mappings if item.mapping_id == second.mapping_id).active)
        self.assertGreaterEqual(len(self.service.get_mapping_history(self.media.anilist_id)), 3)

    def test_clear_mapping_preserves_history(self):
        mapping = self.confirm()
        self.service.clear_mapping(mapping.mapping_id)
        self.assertEqual(self.repo.list_mappings("default", self.media.anilist_id), ())
        self.assertTrue(self.repo.list_mappings("default", self.media.anilist_id, include_inactive=True))
        self.assertTrue(any("CLEARED" in row["event_type"] for row in self.service.get_mapping_history(self.media.anilist_id)))

    def test_clear_broken_mapping_is_allowed_and_preserves_decision(self):
        mapping = self.confirm()
        self.service.check_confirmed_mappings(self.media, snapshot(), aired_episode_count=12)
        self.service.clear_mapping(mapping.mapping_id)
        self.assertEqual(self.repo.list_mappings("default", self.media.anilist_id), ())
        self.assertEqual(
            self.repo.active_manual_decision("default", self.media.anilist_id).value,
            "CLEAR_CONFIRMED_MAPPING",
        )

    def test_repeated_missing_scan_records_one_broken_history_event(self):
        self.confirm()
        self.service.check_confirmed_mappings(self.media, snapshot(), aired_episode_count=12)
        self.service.check_confirmed_mappings(self.media, snapshot(), aired_episode_count=12)
        broken = [
            row for row in self.service.get_mapping_history(self.media.anilist_id)
            if row["event_type"].startswith("MAPPING_BROKEN:")
        ]
        self.assertEqual(len(broken), 1)

    def test_archived_entry_creates_no_candidates_or_reviews(self):
        result = self.service.generate_candidates(
            self.media, self.inventory, session_id="archived", archived=True,
        )
        self.assertEqual(result.candidates, ())
        self.assertEqual(self.repo.list_reviews("default", anilist_id=self.media.anilist_id), ())

    def test_partial_and_canceled_inventory_state_is_persisted_on_session(self):
        partial = self.service.generate_candidates(
            self.media, snapshot(inventory_item(), partial=True), session_id="partial",
        )
        canceled_inventory = replace(self.inventory, canceled=True)
        canceled = self.service.generate_candidates(
            self.media, canceled_inventory, session_id="canceled",
        )
        self.assertTrue(self.repo.get_session(partial.session.session_id).partial)
        self.assertTrue(self.repo.get_session(canceled.session.session_id).canceled)

    def test_diagnostics_use_session_profile_and_export_only_relative_path(self):
        generated = self.generate(profile_id="profile-one")
        self.service.confirm_mapping(
            generated.candidates[0].candidate_id,
            self.media,
            self.inventory,
            profile_id="profile-one",
        )
        diagnostics = self.service.candidate_diagnostics(generated.candidates[0].candidate_id)
        self.assertEqual(diagnostics["mapping_history_count"], 1)
        self.assertIn("relative_path", diagnostics["target"])
        self.assertNotIn("normalized_path", diagnostics["target"])
        self.assertTrue(diagnostics["normalized_title_variants"])

    def test_mark_not_on_server_is_persistent_normal_decision(self):
        self.confirm()
        self.service.mark_not_on_server(self.media.anilist_id, reason="not present")
        restarted = MatchingRepository(self.db)
        self.assertEqual(restarted.active_manual_decision("default", self.media.anilist_id).value, "NOT_ON_SERVER")
        self.assertEqual(restarted.list_mappings("default", self.media.anilist_id), ())
        self.assertEqual(restarted.list_reviews("default", anilist_id=self.media.anilist_id), ())

    def test_weak_candidate_does_not_reverse_not_on_server_decision(self):
        self.service.mark_not_on_server(self.media.anilist_id)
        result = self.generate(session_id="after-not-on-server")
        self.assertFalse(any(candidate.preselected for candidate in result.candidates))
        self.assertEqual(self.repo.active_manual_decision("default", self.media.anilist_id).value, "NOT_ON_SERVER")

    def test_no_valid_candidate_and_skip_are_distinct_decisions(self):
        self.service.mark_no_valid_candidate(self.media.anilist_id)
        self.assertEqual(self.repo.active_manual_decision("default", self.media.anilist_id).value, "NO_VALID_CANDIDATE")
        self.service.skip_matching_for_now(self.media.anilist_id)
        self.assertEqual(self.repo.active_manual_decision("default", self.media.anilist_id).value, "SKIP_FOR_NOW")

    def test_failed_repository_write_rolls_back_transaction(self):
        candidate = self.generate().candidates[0]
        before = self.repo.list_mappings("default", self.media.anilist_id)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.repo.connect() as connection:
                connection.execute("INSERT INTO media_server_mappings(mapping_id) VALUES('invalid')")
        self.assertEqual(self.repo.list_mappings("default", self.media.anilist_id), before)


if __name__ == "__main__":
    unittest.main()
