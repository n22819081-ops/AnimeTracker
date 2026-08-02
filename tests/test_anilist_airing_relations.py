from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from anime_tracker.domain.enums import AniListStatus, RelationDirection, RelationType
from anime_tracker.services.anilist.airing import compare_airing_snapshots, finished_evidence_warnings, parse_airing_rows
from anime_tracker.services.anilist.models import AiringEventType, AniListAiringEpisode, AniListRelation, parse_media
from anime_tracker.services.anilist.relations import (
    branch_entries,
    build_franchise_graph,
    connected_component,
    connected_components,
    likely_main_series_chain,
    related_tracked_entries,
    suggest_franchise_groups,
)

from anilist_helpers import NOW, fixture


def episode(number, offset_hours, *, aired=False, media_id=1002):
    return AniListAiringEpisode(media_id, number, NOW + timedelta(hours=offset_hours), has_aired=aired, schedule_id=5000 + number)


def event_types(old, new, **kwargs):
    return {item.event_type for item in compare_airing_snapshots(old, new, **kwargs)}


class AiringScheduleTests(unittest.TestCase):
    def test_upcoming_schedule_parses_timezone_aware(self):
        rows = fixture("airing_cases.json")["upcoming"]
        parsed = parse_airing_rows(rows, NOW)
        self.assertEqual(parsed[0].episode_number, 4)
        self.assertIsNotNone(parsed[0].airing_at.tzinfo)

    def test_newly_aired_episode(self):
        old = (episode(3, -1, aired=False),)
        new = (episode(3, -1, aired=True),)
        self.assertEqual(event_types(old, new), {AiringEventType.NEW_EPISODE_AIRED})

    def test_new_upcoming_episode_is_scheduled(self):
        self.assertEqual(event_types((), (episode(4, 24),)), {AiringEventType.NEXT_EPISODE_SCHEDULED})

    def test_repeated_snapshot_produces_no_event(self):
        current = (episode(4, 24),)
        self.assertEqual(compare_airing_snapshots(current, current), ())

    def test_changed_timestamp(self):
        old = (episode(4, 24),)
        earlier = (episode(4, 12),)
        self.assertIn(AiringEventType.AIRING_TIME_CHANGED, event_types(old, earlier))

    def test_delayed_episode(self):
        old = (episode(4, 24),)
        later = (episode(4, 48),)
        self.assertIn(AiringEventType.EPISODE_DELAYED, event_types(old, later))

    def test_removed_future_schedule(self):
        self.assertEqual(event_types((episode(4, 24),), ()), {AiringEventType.AIRING_SCHEDULE_REMOVED})

    def test_season_started_airing(self):
        types = event_types((), (), previous_status=AniListStatus.NOT_YET_RELEASED, current_status=AniListStatus.RELEASING)
        self.assertEqual(types, {AiringEventType.SEASON_STARTED_AIRING})

    def test_final_episode_and_finished_status(self):
        final = episode(12, -1, aired=True)
        types = event_types((), (final,), previous_status=AniListStatus.RELEASING, current_status=AniListStatus.FINISHED, expected_episode_count=12)
        self.assertIn(AiringEventType.NEW_EPISODE_AIRED, types)
        self.assertIn(AiringEventType.SERIES_FINISHED_AIRING, types)

    def test_finished_show_with_no_future_schedule(self):
        events = compare_airing_snapshots((), (), previous_status=AniListStatus.RELEASING, current_status=AniListStatus.FINISHED, expected_episode_count=12)
        finished = next(item for item in events if item.event_type == AiringEventType.SERIES_FINISHED_AIRING)
        self.assertIn(("no_future_schedule", "True"), finished.details)

    def test_missing_schedule_is_not_itself_an_event(self):
        self.assertEqual(compare_airing_snapshots((), ()), ())

    def test_provider_status_conflicts_produce_warnings_not_coverage_changes(self):
        warnings = finished_evidence_warnings(status=AniListStatus.FINISHED, end_date_reached=True, final_expected_episode_aired=True, future_schedule_exists=True)
        self.assertTrue(warnings)
        self.assertNotIn("server", warnings[0].casefold())

    def test_provider_outage_same_cached_snapshot_has_no_false_transition(self):
        cached = (episode(4, 24),)
        self.assertEqual(compare_airing_snapshots(cached, cached, previous_status=AniListStatus.RELEASING, current_status=AniListStatus.RELEASING), ())


class FranchiseGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = fixture("media_cases.json")
        cls.media = {key: parse_media(value, NOW) for key, value in cases.items()}
        cls.relations = tuple(cls.media["finished_tv"].relations) + tuple(cls.media["airing_tv"].relations)
        cls.graph = build_franchise_graph(cls.relations, (1002, 1003, 1004, 1005, 1008, 9999))

    def test_prequel_sequel_chain(self):
        self.assertEqual(likely_main_series_chain(self.graph, 1003), (1002, 1003))

    def test_movie_ova_and_side_story_branches(self):
        self.assertEqual(branch_entries(self.graph, 1003), (1004, 1005, 1008))

    def test_direction_is_preserved(self):
        self.assertTrue(all(edge.direction == RelationDirection.OUTBOUND for edge in self.graph.edges))

    def test_connected_component(self):
        self.assertEqual(connected_component(self.graph, 1003), frozenset({1002, 1003, 1004, 1005, 1008}))

    def test_similar_or_disconnected_title_is_not_grouped(self):
        self.assertEqual(connected_component(self.graph, 9999), frozenset({9999}))
        components = connected_components(self.graph)
        self.assertIn(frozenset({9999}), components)

    def test_related_tracked_entries(self):
        self.assertEqual(related_tracked_entries(self.graph, 1003, {1002, 1003, 8888}), (1002, 1003))

    def test_group_suggestion_uses_relation_evidence_only(self):
        media = {item.anilist_id: item for item in self.media.values()}
        groups = suggest_franchise_groups(self.graph, media)
        self.assertEqual(len(groups), 1)
        self.assertNotIn(9999, groups[0].member_anilist_ids)
        self.assertTrue(groups[0].relation_evidence)

    def test_alternative_relation_is_marked_ambiguous(self):
        edge = AniListRelation(1, 2, RelationType.ALTERNATIVE, retrieved_at=NOW)
        graph = build_franchise_graph((edge,))
        self.assertTrue(graph.warnings)

    def test_graph_has_no_jellyfin_season_assignment(self):
        for edge in self.graph.edges:
            self.assertFalse(hasattr(edge, "season_number"))


if __name__ == "__main__":
    unittest.main()
