from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from anime_tracker.domain.enums import LibraryKind
from anime_tracker.services.anilist.cancellation import CancellationToken
from anime_tracker.services.server_inventory import (
    DiagnosticCode,
    FileClassification,
    FilesystemInventoryService,
    LibraryRoot,
    RootScanStatus,
    SpecialKind,
)


class _ScandirContext:
    def __init__(self, entries):
        self.entries = entries

    def __enter__(self):
        return iter(self.entries)

    def __exit__(self, *_args):
        return False


class _CancelAfter:
    def __init__(self, checks):
        self.remaining = checks

    def is_cancelled(self):
        self.remaining -= 1
        return self.remaining <= 0


class ServerInventoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def root(self, name="TV", kind=LibraryKind.TV):
        path = self.base / name
        path.mkdir(exist_ok=True)
        return LibraryRoot(name, str(path), kind)

    @staticmethod
    def touch(path: Path, content=b""):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_empty_root_is_distinct_from_missing_root(self):
        empty = self.root()
        missing = LibraryRoot("Missing", str(self.base / "missing"), LibraryKind.TV)
        snapshot = FilesystemInventoryService().scan([empty, missing])
        statuses = {result.root.label: result.status for result in snapshot.roots}
        self.assertEqual(statuses, {"Missing": RootScanStatus.MISSING, "TV": RootScanStatus.EMPTY})

    def test_inaccessible_root_is_honestly_reported(self):
        root = self.root()

        def denied(_path):
            raise PermissionError("private detail")

        result = FilesystemInventoryService(stat=denied).scan([root]).roots[0]
        self.assertEqual(result.status, RootScanStatus.INACCESSIBLE)
        self.assertEqual(result.diagnostics[0].code, DiagnosticCode.ROOT_INACCESSIBLE)
        self.assertNotIn("private detail", result.diagnostics[0].message)

    def test_ordinary_multiseason_series_preserves_season_identity(self):
        root = self.root()
        show = Path(root.path) / "Example Show (2024)"
        self.touch(show / "Season 01" / "Example.S01E01.mkv")
        self.touch(show / "Season 02" / "Example.S02E01.mkv")
        item = FilesystemInventoryService().scan([root]).items[0]
        self.assertEqual(item.year, 2024)
        self.assertEqual([season.season_number for season in item.seasons], [1, 2])
        self.assertEqual(item.seasons[0].present_episode_numbers, frozenset({1}))
        self.assertEqual(item.seasons[1].present_episode_numbers, frozenset({1}))

    def test_empty_show_and_season_are_inventory_facts_not_coverage(self):
        root = self.root()
        (Path(root.path) / "Empty Show" / "Season 02").mkdir(parents=True)
        result = FilesystemInventoryService().scan([root])
        self.assertEqual(result.roots[0].status, RootScanStatus.COMPLETE)
        self.assertEqual(result.items[0].title, "Empty Show")
        self.assertEqual(result.items[0].seasons[0].season_number, 2)
        self.assertEqual(result.items[0].seasons[0].files, ())

    def test_season_one_never_supplies_season_two_coverage(self):
        root = self.root()
        self.touch(Path(root.path) / "Example" / "Season 01" / "Example.S01E01.mkv")
        item = FilesystemInventoryService().scan([root]).items[0]
        self.assertEqual({season.season_number for season in item.seasons}, {1})
        self.assertNotIn(2, {season.season_number for season in item.seasons})

    def test_nested_episode_paths_are_scanned(self):
        root = self.root("Anime")
        self.touch(Path(root.path) / "Series" / "Season 02" / "Video" / "Series.S02E03.mkv")
        season = FilesystemInventoryService().scan([root]).items[0].seasons[0]
        self.assertEqual((season.season_number, season.present_episode_numbers), (2, frozenset({3})))

    def test_season_zero_specials_are_separate_from_regular_seasons(self):
        root = self.root()
        show = Path(root.path) / "Example"
        self.touch(show / "Season 00" / "Example.S00E01.mkv")
        self.touch(show / "Season 01" / "Example.S01E01.mkv")
        item = FilesystemInventoryService().scan([root]).items[0]
        self.assertEqual([season.season_number for season in item.seasons], [1])
        self.assertEqual(item.specials[0].kind, SpecialKind.SPECIAL)
        self.assertEqual(item.specials[0].files[0].episode_numbers, (1,))

    def test_ova_and_ona_layouts_are_observed_without_mapping(self):
        root = self.root("Anime")
        show = Path(root.path) / "Example"
        self.touch(show / "OVA" / "01 - OVA.mkv")
        self.touch(show / "ONA" / "01 - ONA.mkv")
        item = FilesystemInventoryService().scan([root]).items[0]
        self.assertEqual({group.kind for group in item.specials}, {SpecialKind.OVA, SpecialKind.ONA})
        self.assertFalse(hasattr(item, "anilist_id"))

    def test_multi_episode_file_records_every_episode_number(self):
        root = self.root()
        self.touch(Path(root.path) / "Example" / "Season 01" / "Example.S01E01-E03.mkv")
        season = FilesystemInventoryService().scan([root]).items[0].seasons[0]
        self.assertEqual(season.present_episode_numbers, frozenset({1, 2, 3}))

    def test_duplicate_episode_numbers_remain_visible_as_separate_files(self):
        root = self.root()
        folder = Path(root.path) / "Example" / "Season 01"
        self.touch(folder / "Example.S01E01.mkv")
        self.touch(folder / "Example.S01E01.version2.mp4")
        season = FilesystemInventoryService().scan([root]).items[0].seasons[0]
        self.assertEqual(len(season.files), 2)
        self.assertEqual([item.episode_numbers for item in season.files], [(1,), (1,)])

    def test_movie_folder_and_standalone_movie_layouts(self):
        root = self.root("Movies", LibraryKind.MOVIE)
        self.touch(Path(root.path) / "Movie One (2024)" / "Movie.One.2024.mkv")
        self.touch(Path(root.path) / "Movie Two (2025).mp4")
        items = FilesystemInventoryService().scan([root]).items
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.movie_files for item in items))
        self.assertEqual({item.year for item in items}, {2024, 2025})

    def test_multiple_media_extensions_are_supported(self):
        root = self.root()
        show = Path(root.path) / "Example" / "Season 01"
        for number, extension in enumerate((".mkv", ".mp4", ".avi", ".m2ts", ".webm"), start=1):
            self.touch(show / f"Example.S01E{number:02d}{extension}")
        item = FilesystemInventoryService().scan([root]).items[0]
        self.assertEqual(item.seasons[0].present_episode_numbers, frozenset(range(1, 6)))

    def test_unrecognized_media_is_retained_conservatively(self):
        root = self.root()
        self.touch(Path(root.path) / "Example" / "release-name-without-number.mkv")
        result = FilesystemInventoryService().scan([root])
        self.assertEqual(result.items[0].unrecognized_media[0].classification, FileClassification.UNRECOGNIZED_MEDIA)
        self.assertIn(DiagnosticCode.UNRECOGNIZED_MEDIA, {item.code for item in result.roots[0].diagnostics})

    def test_artwork_subtitles_metadata_samples_and_extras_are_ignored(self):
        root = self.root()
        show = Path(root.path) / "Example"
        self.touch(show / "poster.jpg")
        self.touch(show / "show.nfo")
        self.touch(show / "Season 01" / "Example.S01E01.srt")
        self.touch(show / "Samples" / "sample.mkv")
        self.touch(show / "Extras" / "interview.mp4")
        result = FilesystemInventoryService().scan([root])
        self.assertEqual(result.roots[0].status, RootScanStatus.COMPLETE)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.files, ())

    def test_unicode_punctuation_apostrophes_and_brackets_are_preserved(self):
        root = self.root("Anime")
        title = "Frieren - Beyond Journey's End [2023] - 葬送のフリーレン"
        self.touch(Path(root.path) / title / "Season 1" / "Episode.S01E01.mkv")
        item = FilesystemInventoryService().scan([root]).items[0]
        self.assertEqual(item.title, title)
        self.assertEqual(item.year, 2023)

    def test_partial_directory_failure_retains_successful_items(self):
        root = self.root()
        good = Path(root.path) / "Good"
        blocked = Path(root.path) / "Blocked"
        self.touch(good / "Season 01" / "Good.S01E01.mkv")
        blocked.mkdir()
        real_scandir = os.scandir

        def selective_scandir(path):
            if Path(path).name == "Blocked":
                raise PermissionError("denied")
            return real_scandir(path)

        result = FilesystemInventoryService(scandir=selective_scandir).scan([root]).roots[0]
        self.assertEqual(result.status, RootScanStatus.PARTIAL)
        self.assertEqual([item.title for item in result.items], ["Blocked", "Good"])
        self.assertEqual(result.items[0].seasons, ())
        self.assertIn(DiagnosticCode.ENTRY_INACCESSIBLE, {item.code for item in result.diagnostics})

    def test_file_stat_failure_retains_parsed_filename_and_marks_partial(self):
        root = self.root()
        episode = self.touch(Path(root.path) / "Example" / "Season 01" / "Example.S01E01.mkv")
        real_stat = os.stat

        def selective_stat(path):
            if Path(path) == episode:
                raise PermissionError("denied")
            return real_stat(path)

        result = FilesystemInventoryService(stat=selective_stat).scan([root])
        self.assertEqual(result.roots[0].status, RootScanStatus.PARTIAL)
        self.assertEqual(result.items[0].seasons[0].present_episode_numbers, frozenset({1}))
        self.assertIn(DiagnosticCode.STAT_FAILED, {item.code for item in result.roots[0].diagnostics})

    def test_duplicate_case_variant_paths_are_not_duplicated(self):
        root = self.root()
        self.touch(Path(root.path) / "Example" / "Season 01" / "Example.S01E01.mkv")
        case_variant = LibraryRoot("TV Case Variant", root.path.upper(), LibraryKind.TV)
        result = FilesystemInventoryService().scan([root, case_variant])
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.statistics.duplicate_paths_skipped, 1)

    def test_same_root_encountered_twice_does_not_duplicate_items(self):
        root = self.root()
        self.touch(Path(root.path) / "Example" / "Season 01" / "Example.S01E01.mkv")
        alias = LibraryRoot("TV Alias", root.path.upper(), LibraryKind.TV)
        result = FilesystemInventoryService().scan([root, alias])
        self.assertEqual(len(result.items), 1)

    def test_enumeration_order_does_not_change_snapshot(self):
        root = self.root()
        for title in ("Zulu", "Alpha", "Beta"):
            self.touch(Path(root.path) / title / "Season 01" / f"{title}.S01E01.mkv")
        normal = FilesystemInventoryService().scan([root])
        real_scandir = os.scandir

        def reversed_scandir(path):
            with real_scandir(path) as iterator:
                return _ScandirContext(list(reversed(list(iterator))))

        reversed_result = FilesystemInventoryService(scandir=reversed_scandir).scan([root])
        self.assertEqual(normal, reversed_result)

    def test_unchanged_previous_snapshot_reuses_file_parse(self):
        root = self.root()
        self.touch(Path(root.path) / "Example" / "Season 01" / "Example.S01E01.mkv", b"one")
        service = FilesystemInventoryService()
        first = service.scan([root])
        second = service.scan([root], previous_snapshot=first)
        self.assertEqual(second.statistics.files_reused, 1)
        self.assertEqual(first.items, second.items)

    def test_stable_item_id_does_not_depend_on_display_label(self):
        root = self.root()
        self.touch(Path(root.path) / "Example" / "Season 01" / "Example.S01E01.mkv")
        service = FilesystemInventoryService()
        first = service.scan([root]).items[0]
        renamed = service.scan([LibraryRoot("Renamed Label", root.path, LibraryKind.TV)]).items[0]
        self.assertEqual(first.item_id, renamed.item_id)

    def test_changed_file_is_reparsed(self):
        root = self.root()
        episode = self.touch(Path(root.path) / "Example" / "Season 01" / "Example.S01E01.mkv", b"one")
        service = FilesystemInventoryService()
        first = service.scan([root])
        episode.write_bytes(b"changed-size")
        second = service.scan([root], previous_snapshot=first)
        self.assertEqual(second.statistics.files_reused, 0)

    def test_pre_canceled_scan_does_not_read_root(self):
        root = self.root()
        token = CancellationToken()
        token.cancel()
        result = FilesystemInventoryService().scan([root], token=token)
        self.assertTrue(result.canceled)
        self.assertEqual(result.roots[0].status, RootScanStatus.CANCELED)
        self.assertEqual(result.statistics.roots_scanned, 0)

    def test_cancellation_during_scan_returns_partial_observations(self):
        root = self.root()
        for number in range(1, 30):
            self.touch(Path(root.path) / "Example" / "Season 01" / f"Example.S01E{number:02d}.mkv")
        result = FilesystemInventoryService().scan([root], token=_CancelAfter(12))
        self.assertTrue(result.canceled)
        self.assertEqual(result.roots[0].status, RootScanStatus.CANCELED)

    def test_symlink_or_junction_entry_is_skipped_without_recursion(self):
        root = self.root()
        target = Path(root.path) / "Real"
        self.touch(target / "Season 01" / "Real.S01E01.mkv")
        link = Path(root.path) / "Link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            class FakeEntry:
                name = "Link"
                path = str(link)

                @staticmethod
                def is_symlink():
                    return True

            real_scandir = os.scandir

            def injected(path):
                with real_scandir(path) as iterator:
                    entries = list(iterator)
                if Path(path) == Path(root.path):
                    entries.append(FakeEntry())
                return _ScandirContext(entries)

            result = FilesystemInventoryService(scandir=injected).scan([root])
        else:
            result = FilesystemInventoryService().scan([root])
        self.assertEqual(len(result.items), 1)
        self.assertIn(DiagnosticCode.SYMLINK_SKIPPED, {item.code for item in result.roots[0].diagnostics})

    def test_domain_adapter_supplies_episode_facts_without_status_decision(self):
        root = self.root()
        self.touch(Path(root.path) / "Example" / "Season 02" / "Example.S02E01.mkv")
        item = FilesystemInventoryService().scan([root]).items[0].to_domain_model()
        self.assertEqual(item.seasons[0].season_number, 2)
        self.assertEqual(item.seasons[0].episodes[0].episode_number, 1)
        self.assertTrue(item.path_exists)

    def test_scan_does_not_modify_fixture_paths_or_file_content(self):
        root = self.root("Anime")
        episode = self.touch(
            Path(root.path) / "Read Only" / "Season 01" / "Read.Only.S01E01.mkv",
            b"media-bytes",
        )
        before_paths = sorted(str(path.relative_to(root.path)) for path in Path(root.path).rglob("*"))
        before_bytes = episode.read_bytes()
        before_mtime = episode.stat().st_mtime_ns
        FilesystemInventoryService().scan([root])
        after_paths = sorted(str(path.relative_to(root.path)) for path in Path(root.path).rglob("*"))
        self.assertEqual(after_paths, before_paths)
        self.assertEqual(episode.read_bytes(), before_bytes)
        self.assertEqual(episode.stat().st_mtime_ns, before_mtime)


if __name__ == "__main__":
    unittest.main()
