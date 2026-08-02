import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_tracker.constants import (
    REVIEW_NO_MATCH,
    SERVER_MISSING_NEEDS_REVIEW,
    SERVER_NOT_FOUND,
    SERVER_NOT_ON_SERVER,
    SERVER_ON_SERVER,
    SERVER_ON_SERVER_MANUAL,
    TRACKER_AIRING,
    TRACKER_NEEDS_REVIEW,
    TRACKER_ON_SERVER,
    TRACKER_READY,
)
from anime_tracker.database import Database
from anime_tracker.models import AnimeRecord
from anime_tracker.path_utils import normalize_windows_path
from anime_tracker.review import build_review_state
from anime_tracker.scanner import (
    confirmed_match_has_evidence,
    infer_tracked_seasons,
    match_record,
    scan_roots,
)


def record(anilist_id: int, year: int, status: str = TRACKER_READY, relation_label: str = "") -> AnimeRecord:
    return AnimeRecord(
        english_title="Shared Franchise",
        romaji_title="Shared Franchise",
        native_title="",
        alternate_titles=["Shared Franchise: Subtitle"],
        anilist_id=anilist_id,
        format="TV",
        season="SPRING",
        year=year,
        total_episodes=12,
        airing_status="FINISHED",
        start_date=f"{year}-04-01",
        expected_end_date=f"{year}-06-30",
        cover_image_url="",
        anilist_url=f"https://anilist.co/anime/{anilist_id}",
        tracker_status=status,
        relation_label=relation_label,
    )


def airing_record(anilist_id: int, year: int) -> AnimeRecord:
    item = record(anilist_id, year, TRACKER_AIRING)
    item.airing_status = "RELEASING"
    return item


class MatchingWorkflowTests(unittest.TestCase):
    def test_shared_show_folder_does_not_mark_missing_future_season_on_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tv = root / "tv"
            movies = root / "movies"
            show = tv / "Shared Franchise (2022)"
            (show / "Season 01").mkdir(parents=True)
            movies.mkdir()
            db = Database(root / "tracker.db")
            first = db.upsert_anime(record(1001, 2022, relation_label="Season 1"))
            second = db.upsert_anime(record(1002, 2022, relation_label="Season 2"))
            candidates = scan_roots(str(tv), str(movies))

            first_result = match_record(db.get(first), candidates)
            second_result = match_record(db.get(second), candidates)

            self.assertEqual(first_result.confidence, "confident")
            self.assertEqual(second_result.confidence, "none")

    def test_shared_folder_scan_marks_only_season_with_evidence_on_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tv = root / "tv"
            movies = root / "movies"
            show = tv / "Shared Franchise (2022)"
            (show / "Season 01").mkdir(parents=True)
            movies.mkdir()
            db = Database(root / "tracker.db")
            first = db.upsert_anime(record(1001, 2022, relation_label="Season 1"))
            second = db.upsert_anime(record(1002, 2022, relation_label="Season 2"))
            candidates = scan_roots(str(tv), str(movies))
            for row_id, season_number in ((first, 1), (second, 2)):
                row = db.get(row_id)
                result = match_record(row, candidates, db.rejected_paths_for(row["anilist_id"]), season_number)
                if result.confidence == "confident":
                    db.set_on_server(row_id, result.path, SERVER_ON_SERVER, event="Automatic match", confirmation_type="automatic")
                else:
                    db.mark_no_match_found(row_id)

            self.assertEqual(db.get(first)["tracker_status"], TRACKER_ON_SERVER)
            self.assertEqual(db.get(second)["server_status"], SERVER_NOT_FOUND)
            self.assertNotEqual(db.get(second)["tracker_status"], TRACKER_ON_SERVER)

    def test_rescan_clears_unsupported_automatic_future_season_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tv = root / "tv"
            movies = root / "movies"
            show = tv / "Shared Franchise (2022)"
            (show / "Season 01").mkdir(parents=True)
            movies.mkdir()
            db = Database(root / "tracker.db")
            second = db.upsert_anime(record(1002, 2022, relation_label="Season 2"))
            db.set_on_server(second, str(show), SERVER_ON_SERVER, event="Old automatic match", confirmation_type="automatic")
            candidates = scan_roots(str(tv), str(movies))
            confirmed = db.confirmed_match_for(1002)

            self.assertFalse(confirmed_match_has_evidence(confirmed, candidates, 2))
            db.clear_unsupported_automatic_match(second, str(show))
            result = match_record(db.get(second), candidates, db.rejected_paths_for(1002), 2)
            self.assertEqual(result.confidence, "none")
            db.mark_no_match_found(second)

            self.assertIsNone(db.confirmed_match_for(1002))
            self.assertEqual(db.get(second)["server_status"], SERVER_NOT_FOUND)
            self.assertEqual(db.get(second)["tracker_status"], TRACKER_READY)

    def test_rejecting_future_season_removes_confirmation_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "tv" / "Shared Franchise (2022)"
            (show / "Season 01").mkdir(parents=True)
            movies = root / "movies"
            movies.mkdir()
            db = Database(root / "tracker.db")
            second = db.upsert_anime(record(1002, 2022, relation_label="Season 2"))
            db.set_on_server(second, str(show), SERVER_ON_SERVER, event="Old automatic match", confirmation_type="automatic")

            db.reject_match(1002, str(show))
            restarted = Database(root / "tracker.db")
            candidates = scan_roots(str(root / "tv"), str(movies))
            result = match_record(restarted.get(second), candidates, restarted.rejected_paths_for(1002), 2)

            self.assertIsNone(restarted.confirmed_match_for(1002))
            self.assertEqual(result.confidence, "none")
            self.assertEqual(restarted.get(second)["server_status"], SERVER_NOT_FOUND)

    def test_not_on_server_future_season_is_not_overwritten_on_rescan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "tv" / "Shared Franchise (2022)"
            (show / "Season 01").mkdir(parents=True)
            movies = root / "movies"
            movies.mkdir()
            db = Database(root / "tracker.db")
            second = db.upsert_anime(record(1002, 2022, relation_label="Season 2"))
            db.set_on_server(second, str(show), SERVER_ON_SERVER, event="Old automatic match", confirmation_type="automatic")
            db.mark_not_on_server(second, str(show))

            candidates = scan_roots(str(root / "tv"), str(movies))
            result = match_record(db.get(second), candidates, db.rejected_paths_for(1002), 2)
            self.assertIsNone(db.confirmed_match_for(1002))
            self.assertEqual(result.confidence, "none")
            self.assertEqual(db.get(second)["server_status"], SERVER_NOT_ON_SERVER)

    def test_manual_season_confirmation_remains_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "tv" / "Shared Franchise (2022)"
            (show / "Season 01").mkdir(parents=True)
            movies = root / "movies"
            movies.mkdir()
            db = Database(root / "tracker.db")
            second = db.upsert_anime(record(1002, 2022, relation_label="Season 2"))
            db.confirm_match(second, str(show))
            confirmed = db.confirmed_match_for(1002)

            self.assertEqual(confirmed["confirmation_type"], "manual")
            self.assertTrue(confirmed_match_has_evidence(confirmed, scan_roots(str(root / "tv"), str(movies)), 2))
            self.assertEqual(db.get(second)["tracker_status"], TRACKER_ON_SERVER)

    def test_both_seasons_match_when_both_season_folders_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tv = root / "tv"
            movies = root / "movies"
            show = tv / "Shared Franchise (2022)"
            (show / "Season 01").mkdir(parents=True)
            (show / "S02").mkdir()
            movies.mkdir()
            db = Database(root / "tracker.db")
            first = db.upsert_anime(record(1001, 2022, relation_label="Season 1"))
            second = db.upsert_anime(record(1002, 2022, relation_label="Season 2"))
            candidates = scan_roots(str(tv), str(movies))

            self.assertEqual(match_record(db.get(first), candidates).confidence, "confident")
            self.assertEqual(match_record(db.get(second), candidates).confidence, "confident")

    def test_same_title_sequel_rows_receive_distinct_inferred_seasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            first = db.upsert_anime(record(1001, 2022, relation_label="Prequel"))
            second = db.upsert_anime(record(1002, 2026, relation_label="Sequel"))
            inferred = infer_tracked_seasons([db.get(first), db.get(second)])
            self.assertEqual(inferred, {1001: 1, 1002: 2})

    def test_single_season_show_without_explicit_season_keeps_existing_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022))
            candidates = scan_roots_for_paths(Path(tmp), ["Shared Franchise (2022)"])
            self.assertEqual(match_record(db.get(row_id), candidates).confidence, "confident")

    def test_manual_season_one_match_does_not_propagate_to_season_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Shared Franchise (2022)"
            show.mkdir()
            db = Database(root / "tracker.db")
            first = db.upsert_anime(record(1001, 2022, relation_label="Season 1"))
            second = db.upsert_anime(record(1002, 2022, relation_label="Season 2"))

            db.confirm_match(first, str(show))

            self.assertEqual(db.get(first)["tracker_status"], TRACKER_ON_SERVER)
            self.assertEqual(db.get(second)["server_status"], SERVER_NOT_FOUND)
            self.assertIsNone(db.confirmed_match_for(1002))

    def test_fresh_server_match_records_confirmation_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Shared Franchise"
            show.mkdir()
            db = Database(root / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022))
            db.set_on_server(row_id, str(show), confirmation_type="automatic")

            self.assertEqual(db.confirmed_match_for(1001)["confirmation_type"], "automatic")

    def test_legacy_server_match_migration_preserves_manual_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tracker.db"
            show = str(root / "Shared Franchise")
            connection = sqlite3.connect(path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE server_matches (
                        anilist_id INTEGER PRIMARY KEY,
                        path TEXT NOT NULL,
                        season_label TEXT NOT NULL DEFAULT '',
                        confirmed_at TEXT NOT NULL
                    );
                    CREATE TABLE status_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        anilist_id INTEGER,
                        event TEXT NOT NULL,
                        previous_status TEXT NOT NULL DEFAULT '',
                        new_status TEXT NOT NULL DEFAULT '',
                        server_path TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );
                    """
                )
                connection.execute("INSERT INTO server_matches VALUES(?, ?, ?, ?)", (1001, show, "Season 2", "2026-01-01"))
                connection.execute(
                    "INSERT INTO status_history(anilist_id, event, server_path, created_at) VALUES(?, ?, ?, ?)",
                    (1001, "Server path confirmed", show, "2026-01-01"),
                )
                connection.commit()
            finally:
                connection.close()

            with patch("anime_tracker.database.BACKUP_DIR", root / "backups"):
                migrated = Database(path)

            self.assertEqual(migrated.confirmed_match_for(1001)["confirmation_type"], "manual")

    def test_two_seasons_with_same_english_title_remain_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            first = db.upsert_anime(record(1001, 2022, relation_label="Season 1"))
            second = db.upsert_anime(record(1002, 2026, status=TRACKER_AIRING, relation_label="Sequel"))

            self.assertNotEqual(first, second)
            rows = db.rows()
            self.assertEqual({row["anilist_id"] for row in rows}, {1001, 1002})
            self.assertEqual(db.get(first)["relation_label"], "Season 1")
            self.assertEqual(db.get(second)["relation_label"], "Sequel")

    def test_multiple_anilist_entries_can_share_one_jellyfin_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Shared Franchise (2022)"
            show.mkdir()
            db = Database(root / "tracker.db")
            first = db.upsert_anime(record(1001, 2022, relation_label="Season 1"))
            second = db.upsert_anime(record(1002, 2026, relation_label="Sequel"))

            db.confirm_match(first, str(show))
            db.confirm_match(second, str(show))

            self.assertEqual(db.get(first)["detected_server_path"], str(show))
            self.assertEqual(db.get(second)["detected_server_path"], str(show))
            self.assertEqual(db.get(first)["tracker_status"], TRACKER_ON_SERVER)
            self.assertEqual(db.get(second)["tracker_status"], TRACKER_ON_SERVER)

    def test_manual_match_persistence_and_later_scan_attach_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tv = root / "tv"
            movies = root / "movies"
            tv.mkdir()
            movies.mkdir()
            folder = tv / "Shared Franchise (2022)"
            folder.mkdir()
            db = Database(root / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022))
            db.set_on_server(row_id, "", SERVER_ON_SERVER_MANUAL, "Manual confirmation.", "Manually marked on server")

            self.assertEqual(db.get(row_id)["tracker_status"], TRACKER_ON_SERVER)
            self.assertEqual(db.get(row_id)["server_status"], SERVER_ON_SERVER_MANUAL)

            candidates = scan_roots(str(tv), str(movies))
            result = match_record(db.get(row_id), candidates)
            self.assertEqual(result.confidence, "confident")
            db.set_on_server(row_id, result.path, SERVER_ON_SERVER, db.get(row_id)["manual_notes"], "Server path confirmed")

            updated = db.get(row_id)
            self.assertEqual(updated["tracker_status"], TRACKER_ON_SERVER)
            self.assertEqual(updated["server_status"], SERVER_ON_SERVER)
            self.assertEqual(updated["detected_server_path"], str(folder))

    def test_rejecting_incorrect_candidate_removes_it_from_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            db.upsert_anime(record(1001, 2022))
            row = db.rows()[0]
            candidates = match_record(
                row,
                scan_roots_for_paths(Path(tmp), ["Shared Franchise Wrong (2022)"]),
            ).candidates
            db.save_match_candidates(row["anilist_id"], candidates)
            self.assertTrue(db.get_match_candidates(row["anilist_id"]))

            path = db.get_match_candidates(row["anilist_id"])[0]["path"]
            db.reject_match(row["anilist_id"], path)

            self.assertEqual(db.get_match_candidates(row["anilist_id"]), [])

    def test_rejected_match_is_skipped_by_future_scans(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022))
            candidates = scan_roots_for_paths(Path(tmp), ["Shared Franchise (2022)"])
            result = match_record(db.get(row_id), candidates)
            self.assertEqual(result.confidence, "confident")

            db.reject_match(1001, result.path)
            next_result = match_record(db.get(row_id), candidates, db.rejected_paths_for(1001))

            self.assertEqual(next_result.confidence, "none")

    def test_rejected_match_persists_after_database_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tracker.db"
            db = Database(db_path)
            path = str(Path(tmp) / "TV" / "Shared Franchise (2022)") + "\\"
            db.reject_match(1001, path)

            restarted = Database(db_path)

            self.assertIn(normalize_windows_path(path), restarted.rejected_paths_for(1001))

    def test_rejecting_one_folder_does_not_block_different_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022))
            root = Path(tmp)
            rejected = root / "tv" / "Shared Franchise Wrong (2022)"
            accepted = root / "tv" / "Shared Franchise (2022)"
            candidates = scan_roots_for_paths(root, [rejected.name, accepted.name])
            db.reject_match(1001, str(rejected))

            result = match_record(db.get(row_id), candidates, db.rejected_paths_for(1001))

            self.assertEqual(result.confidence, "confident")
            self.assertEqual(result.path, str(accepted))

    def test_manual_confirm_overrides_prior_rejection_for_same_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022))
            folder = Path(tmp) / "Shared Franchise (2022)"
            folder.mkdir()
            db.reject_match(1001, str(folder).upper() + "\\")

            db.set_on_server(row_id, str(folder), SERVER_ON_SERVER_MANUAL, event="Manually selected Jellyfin folder")

            self.assertNotIn(normalize_windows_path(str(folder)), db.rejected_paths_for(1001))
            self.assertEqual(db.get(row_id)["tracker_status"], TRACKER_ON_SERVER)

    def test_not_on_server_records_selected_rejected_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022, TRACKER_NEEDS_REVIEW))
            wrong = str(Path(tmp) / "tv" / "Shared Franchise Wrong (2022)")

            db.mark_not_on_server(row_id, wrong)

            self.assertIn(normalize_windows_path(wrong), db.rejected_paths_for(1001))
            self.assertEqual(db.get(row_id)["tracker_status"], TRACKER_READY)

    def test_titles_with_punctuation_and_subtitle_differences_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {
                "english_title": "Shared Franchise: Subtitle!",
                "romaji_title": "Shared Franchise Subtitle",
                "native_title": "",
                "alternate_titles": json.dumps(["Shared Franchise - Subtitle"]),
                "year": 2022,
                "format": "TV",
                "total_episodes": 12,
                "season": "SPRING",
                "relation_label": "",
            }
            candidates = scan_roots_for_paths(Path(tmp), ["Shared Franchise Subtitle (2022)"])
            result = match_record(row, candidates)
            self.assertEqual(result.confidence, "confident")

    def test_on_server_entries_are_excluded_from_other_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            finished = db.upsert_anime(record(1001, 2022, TRACKER_READY))
            airing = db.upsert_anime(record(1002, 2026, TRACKER_AIRING))
            db.set_on_server(finished, r"C:\Media\Shared Franchise", SERVER_ON_SERVER, event="Server path confirmed")
            db.set_on_server(airing, r"C:\Media\Shared Franchise", SERVER_ON_SERVER, event="Server path confirmed")

            rows = db.rows()
            ready_rows = [row for row in rows if row["tracker_status"] == TRACKER_READY]
            airing_rows = [row for row in rows if row["tracker_status"] == TRACKER_AIRING]
            on_server_rows = [row for row in rows if row["tracker_status"] == TRACKER_ON_SERVER]

            self.assertEqual(ready_rows, [])
            self.assertEqual(airing_rows, [])
            self.assertEqual(len(on_server_rows), 2)

    def test_missing_confirmed_path_moves_to_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022))
            missing = Path(tmp) / "missing"
            db.confirm_match(row_id, str(missing))
            db.set_needs_review_missing(row_id, str(missing))

            row = db.get(row_id)
            self.assertEqual(row["tracker_status"], TRACKER_NEEDS_REVIEW)
            self.assertEqual(row["server_status"], SERVER_MISSING_NEEDS_REVIEW)
            self.assertEqual(row["detected_server_path"], str(missing))

    def test_dark_theme_setting_persists_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tracker.db"
            db = Database(path)
            db.set_settings({"theme": "Dark"})
            restarted = Database(path)
            self.assertEqual(restarted.get_settings()["theme"], "Dark")

    def test_zero_candidates_review_state_explains_empty_table(self):
        row = {
            "review_reason": REVIEW_NO_MATCH,
        }
        state = build_review_state(row, [])
        self.assertEqual(state["empty_message"], "No possible Jellyfin matches were found.")
        self.assertIn("folder name may be too different", state["empty_detail"])

    def test_zero_candidates_disables_confirm_match(self):
        row = {
            "review_reason": REVIEW_NO_MATCH,
        }
        state = build_review_state(row, [])
        self.assertFalse(state["confirm_enabled"])
        self.assertFalse(state["reject_enabled"])

    def test_not_on_server_moves_finished_title_to_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022, TRACKER_NEEDS_REVIEW))
            new_status = db.mark_not_on_server(row_id)

            row = db.get(row_id)
            self.assertEqual(new_status, TRACKER_READY)
            self.assertEqual(row["tracker_status"], TRACKER_READY)
            self.assertEqual(row["server_status"], SERVER_NOT_ON_SERVER)

    def test_not_on_server_moves_airing_title_to_airing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(airing_record(1002, 2026))
            db.set_review_state(row_id, "Needs Review", TRACKER_NEEDS_REVIEW, "Possible Jellyfin matches found")
            new_status = db.mark_not_on_server(row_id)

            row = db.get(row_id)
            self.assertEqual(new_status, TRACKER_AIRING)
            self.assertEqual(row["tracker_status"], TRACKER_AIRING)
            self.assertEqual(row["server_status"], SERVER_NOT_ON_SERVER)

    def test_manual_folder_selection_moves_item_to_on_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "Shared Franchise (2022)"
            folder.mkdir()
            db = Database(root / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022, TRACKER_NEEDS_REVIEW))

            db.set_on_server(row_id, str(folder), SERVER_ON_SERVER_MANUAL, event="Manually selected Jellyfin folder")

            row = db.get(row_id)
            self.assertEqual(row["tracker_status"], TRACKER_ON_SERVER)
            self.assertEqual(row["server_status"], SERVER_ON_SERVER_MANUAL)
            self.assertEqual(row["detected_server_path"], str(folder))

    def test_no_match_alone_does_not_trigger_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022, TRACKER_READY))
            result = match_record(db.get(row_id), [])
            self.assertEqual(result.confidence, "none")
            db.mark_no_match_found(row_id)

            row = db.get(row_id)
            self.assertEqual(row["tracker_status"], TRACKER_READY)
            self.assertEqual(row["server_status"], SERVER_NOT_FOUND)
            self.assertEqual(row["review_reason"], REVIEW_NO_MATCH)

    def test_no_match_clears_stale_unconfirmed_detected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1002, 2026, TRACKER_AIRING, relation_label="Season 2"))
            db.set_server_match(row_id, SERVER_NOT_FOUND, TRACKER_AIRING, r"I:\TV\Shared Franchise")

            db.mark_no_match_found(row_id)

            row = db.get(row_id)
            self.assertEqual(row["server_status"], SERVER_NOT_FOUND)
            self.assertEqual(row["detected_server_path"], "")

    def test_no_match_does_not_downgrade_manual_on_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            row_id = db.upsert_anime(record(1001, 2022, TRACKER_READY))
            db.set_on_server(row_id, "", SERVER_ON_SERVER_MANUAL, event="Manually marked on server")
            db.mark_no_match_found(row_id)

            row = db.get(row_id)
            self.assertEqual(row["tracker_status"], TRACKER_ON_SERVER)
            self.assertEqual(row["server_status"], SERVER_ON_SERVER_MANUAL)


def scan_roots_for_paths(root: Path, names: list[str]):
    tv = root / "tv"
    movies = root / "movies"
    tv.mkdir(exist_ok=True)
    movies.mkdir(exist_ok=True)
    for name in names:
        (tv / name).mkdir(exist_ok=True)
    return scan_roots(str(tv), str(movies))


if __name__ == "__main__":
    unittest.main()
