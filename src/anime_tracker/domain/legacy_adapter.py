from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from .enums import (
    AniListStatus,
    CoverageSource,
    MediaKind,
    OverrideSource,
    OverrideType,
    ReviewStatus,
    ServerPresence,
    TrackerWorkflowStatus,
    TrackingContentKind,
)
from .models import (
    AniListMediaIdentity,
    ArchivedLegacyRecord,
    DomainWarning,
    LegacyAdaptation,
    ManualOverride,
    MediaTitle,
    ReviewCase,
    ServerPresenceState,
    StatusDecisionInput,
    TrackedMedia,
    TrackingState,
)


def _value(row: Mapping[str, Any], key: str, default: Any = "") -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def _enum(enum_type: type, value: object, default: object) -> object:
    try:
        return enum_type(str(value))
    except ValueError:
        return default


def _legacy_workflow(value: str) -> TrackerWorkflowStatus:
    return {
        "Upcoming": TrackerWorkflowStatus.UPCOMING,
        "Currently Airing": TrackerWorkflowStatus.CURRENTLY_AIRING,
        "Finished / Ready to Add": TrackerWorkflowStatus.FINISHED_READY_TO_ADD,
        "Movie Theatrical Only": TrackerWorkflowStatus.MOVIE_THEATRICAL_ONLY,
        "Movie Digitally Available": TrackerWorkflowStatus.MOVIE_DIGITALLY_AVAILABLE,
        "On Server": TrackerWorkflowStatus.ON_SERVER,
        "Needs Review": TrackerWorkflowStatus.NEEDS_REVIEW,
        "Archived": TrackerWorkflowStatus.ARCHIVED,
    }.get(value, TrackerWorkflowStatus.UPCOMING)


def _legacy_presence(server_status: str, tracker_status: str) -> ServerPresence:
    if server_status == "Missing - Needs Review":
        return ServerPresence.PATH_MISSING
    if server_status.startswith("On Server") or tracker_status == "On Server":
        return ServerPresence.UNKNOWN_COVERAGE
    return ServerPresence.NOT_FOUND


def _content_kind(media_kind: MediaKind, relation_label: str) -> TrackingContentKind:
    if media_kind == MediaKind.MOVIE:
        return TrackingContentKind.MOVIE
    if media_kind == MediaKind.SPECIAL:
        return TrackingContentKind.SPECIAL
    if media_kind == MediaKind.OVA:
        return TrackingContentKind.OVA
    if media_kind == MediaKind.ONA:
        return TrackingContentKind.ONA
    if "season" in relation_label.casefold() or relation_label.casefold() in {"sequel", "prequel"}:
        return TrackingContentKind.SEASON
    if media_kind in {MediaKind.TV, MediaKind.TV_SHORT}:
        return TrackingContentKind.SERIES
    return TrackingContentKind.UNKNOWN


def adapt_legacy_anime_row(row: Mapping[str, Any]) -> LegacyAdaptation:
    anilist_id = int(_value(row, "anilist_id", 0))
    if anilist_id <= 0:
        raise ValueError("Legacy active anime rows require a positive AniList ID.")
    synonyms: tuple[str, ...] = ()
    raw_synonyms = _value(row, "alternate_titles", "")
    if raw_synonyms:
        try:
            parsed = json.loads(raw_synonyms)
            if isinstance(parsed, list):
                synonyms = tuple(str(item) for item in parsed if str(item).strip())
        except (TypeError, json.JSONDecodeError):
            pass
    media_kind = _enum(MediaKind, _value(row, "format", ""), MediaKind.UNKNOWN)
    anilist_status = _enum(AniListStatus, _value(row, "airing_status", ""), AniListStatus.UNKNOWN)
    identity = AniListMediaIdentity(
        anilist_id=anilist_id,
        titles=MediaTitle(
            str(_value(row, "english_title", "")),
            str(_value(row, "romaji_title", "")),
            str(_value(row, "native_title", "")),
            synonyms,
        ),
        media_kind=media_kind,
        status=anilist_status,
        season=str(_value(row, "season", "")),
        season_year=_value(row, "year", None),
        expected_episodes=_value(row, "total_episodes", None),
        start_date=str(_value(row, "start_date", "")),
        end_date=str(_value(row, "expected_end_date", "")),
        page_url=str(_value(row, "anilist_url", "")),
        cover_image_url=str(_value(row, "cover_image_url", "")),
    )
    legacy_tracker = str(_value(row, "tracker_status", ""))
    legacy_server = str(_value(row, "server_status", ""))
    presence = _legacy_presence(legacy_server, legacy_tracker)
    review_cases: tuple[ReviewCase, ...] = ()
    if legacy_tracker == "Needs Review" or legacy_server in {"Needs Review", "Missing - Needs Review"}:
        review_status = ReviewStatus.MISSING_CONFIRMED_PATH if legacy_server == "Missing - Needs Review" else ReviewStatus.LEGACY_DATA_REVIEW
        review_cases = (ReviewCase(
            f"legacy-review:{anilist_id}", str(_value(row, "id", anilist_id)), review_status,
            "LEGACY_REVIEW_REASON", str(_value(row, "review_reason", "")) or "Legacy review cause was not recorded.",
        ),)
    workflow = _legacy_workflow(legacy_tracker)
    server = ServerPresenceState(
        presence=presence,
        coverage=None,
        mapping_confirmed=legacy_server.startswith("On Server") or legacy_tracker == "On Server",
        path_exists=False if presence == ServerPresence.PATH_MISSING else None,
        explanation_code="LEGACY_MANUAL_CONFIRMATION" if presence == ServerPresence.UNKNOWN_COVERAGE else "LEGACY_NOT_FOUND",
    )
    added_at = None
    raw_added = str(_value(row, "date_added", ""))
    if raw_added:
        try:
            added_at = datetime.fromisoformat(raw_added.replace("Z", "+00:00"))
        except ValueError:
            pass
    tracked = TrackedMedia(
        tracked_id=str(_value(row, "id", anilist_id)),
        identity=identity,
        content_kind=_content_kind(media_kind, str(_value(row, "relation_label", ""))),
        state=TrackingState(workflow, presence, review_cases[0].status if review_cases else ReviewStatus.NONE),
        added_at=added_at,
        notes=str(_value(row, "manual_notes", "")),
        archived_at=added_at if legacy_tracker == "Archived" else None,
        legacy_confirmation_preserved=server.mapping_confirmed,
    )
    warnings: list[DomainWarning] = []
    overrides: tuple[ManualOverride, ...] = ()
    if server.mapping_confirmed:
        warnings.append(DomainWarning("LEGACY_COVERAGE_UNKNOWN", "Legacy On Server confirmation is preserved without inventing episode coverage."))
        if workflow == TrackerWorkflowStatus.ON_SERVER:
            overrides = (ManualOverride(
                f"legacy-on-server:{anilist_id}", tracked.tracked_id,
                OverrideType.FORCE_WORKFLOW_STATUS, TrackerWorkflowStatus.ON_SERVER,
                added_at or datetime(1970, 1, 1, tzinfo=timezone.utc),
                "Preserved legacy manual server confirmation.", OverrideSource.LEGACY,
            ),)
    if anilist_status == AniListStatus.UNKNOWN:
        warnings.append(DomainWarning("UNKNOWN_LEGACY_ANILIST_STATUS", "The legacy AniList status is unknown."))
    return LegacyAdaptation(
        tracked,
        StatusDecisionInput(
            identity=identity,
            server=server,
            review_cases=review_cases,
            overrides=overrides,
            archived=tracked.is_archived,
            movie_theatrical_released=media_kind == MediaKind.MOVIE and str(_value(row, "movie_availability", "unknown")) != "digital",
            movie_digital_available=str(_value(row, "movie_availability", "unknown")) == "digital",
        ),
        review_cases,
        tuple(warnings),
    )


def adapt_archived_legacy_row(row: Mapping[str, Any]) -> ArchivedLegacyRecord:
    raw_id = _value(row, "legacy_anilist_id", None)
    return ArchivedLegacyRecord(
        source_table=str(_value(row, "source_table", "unknown")),
        source_key=str(_value(row, "source_key", "")),
        legacy_anilist_id=int(raw_id) if raw_id is not None else None,
        reason=str(_value(row, "reason", "Manual review required")),
        payload_json=str(_value(row, "payload_json", "{}")),
        requires_manual_review=bool(_value(row, "requires_manual_review", 1)),
    )
