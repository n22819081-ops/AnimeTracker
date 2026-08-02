from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from .enums import (
    AniListStatus,
    ConfidenceLevel,
    CoverageSource,
    LibraryKind,
    MappingConfirmation,
    MappingSource,
    MediaKind,
    OverrideSource,
    OverrideType,
    RejectionScope,
    RelationDirection,
    RelationType,
    ReviewStatus,
    ServerPresence,
    TrackerWorkflowStatus,
    TrackingContentKind,
    TransitionEventType,
)


@dataclass(frozen=True)
class MediaTitle:
    english: str = ""
    romaji: str = ""
    native: str = ""
    synonyms: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        return self.english or self.romaji or self.native or "Untitled"


@dataclass(frozen=True)
class AniListMediaIdentity:
    anilist_id: int
    titles: MediaTitle
    media_kind: MediaKind = MediaKind.UNKNOWN
    status: AniListStatus = AniListStatus.UNKNOWN
    season: str = ""
    season_year: int | None = None
    expected_episodes: int | None = None
    start_date: str = ""
    end_date: str = ""
    page_url: str = ""
    cover_image_url: str = ""


@dataclass(frozen=True)
class MediaRelation:
    source_anilist_id: int
    target_anilist_id: int
    relation_type: RelationType
    provider: str = "AniList"
    direction: RelationDirection = RelationDirection.OUTBOUND
    last_confirmed_at: datetime | None = None


@dataclass(frozen=True)
class FranchiseGroup:
    group_id: str
    display_name: str
    member_anilist_ids: tuple[int, ...] = ()
    relations: tuple[MediaRelation, ...] = ()


@dataclass(frozen=True)
class TrackingState:
    workflow_status: TrackerWorkflowStatus
    server_presence: ServerPresence
    review_status: ReviewStatus = ReviewStatus.NONE
    last_checked_at: datetime | None = None


@dataclass(frozen=True)
class TrackedMedia:
    tracked_id: str
    identity: AniListMediaIdentity
    content_kind: TrackingContentKind = TrackingContentKind.UNKNOWN
    state: TrackingState | None = None
    added_at: datetime | None = None
    notes: str = ""
    archived_at: datetime | None = None
    legacy_confirmation_preserved: bool = False

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


@dataclass(frozen=True)
class ServerEpisode:
    episode_number: int | None
    path: str = ""
    present: bool = True
    is_special: bool = False


@dataclass(frozen=True)
class ServerSeason:
    season_number: int
    episodes: tuple[ServerEpisode, ...] = ()
    path: str = ""


@dataclass(frozen=True)
class ServerMovie:
    path: str
    present: bool = True
    stable_item_id: str = ""


@dataclass(frozen=True)
class ServerLibraryItem:
    item_id: str
    library_kind: LibraryKind
    path: str
    title: str = ""
    year: int | None = None
    seasons: tuple[ServerSeason, ...] = ()
    movie: ServerMovie | None = None
    path_exists: bool | None = None


@dataclass(frozen=True)
class EpisodeCoverage:
    expected_total_episodes: int | None
    aired_episode_count: int | None
    present_episode_numbers: frozenset[int] = frozenset()
    missing_aired_episode_numbers: frozenset[int] = frozenset()
    missing_expected_episode_numbers: frozenset[int] = frozenset()
    duplicate_episode_numbers: frozenset[int] = frozenset()
    unknown_numbered_files: int = 0
    special_episode_numbers: frozenset[int] = frozenset()
    coverage_source: CoverageSource = CoverageSource.UNKNOWN
    coverage_calculated_at: datetime | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServerPresenceState:
    presence: ServerPresence
    coverage: EpisodeCoverage | None = None
    mapping_confirmed: bool = False
    path_exists: bool | None = None
    explanation_code: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MediaServerMapping:
    mapping_id: str
    anilist_id: int
    library_kind: LibraryKind
    path: str = ""
    stable_item_id: str = ""
    season_number: int | None = None
    content_kind: TrackingContentKind = TrackingContentKind.UNKNOWN
    confirmation: MappingConfirmation = MappingConfirmation.PROPOSED
    source: MappingSource = MappingSource.SCANNER
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    notes: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    active: bool = True
    superseded_at: datetime | None = None
    allows_multiple_targets: bool = False

    @property
    def is_confirmed(self) -> bool:
        return self.confirmation != MappingConfirmation.PROPOSED


@dataclass(frozen=True)
class JellyfinFolderMapping:
    library_item_id: str
    folder_path: str
    content_kind: TrackingContentKind
    season_number: int | None = None


@dataclass(frozen=True)
class EpisodeMapping:
    anilist_id: int
    provider_episode_number: int
    server_episode_identity: str
    confirmed: bool = False


@dataclass(frozen=True)
class ManualOverride:
    override_id: str
    tracked_id: str
    override_type: OverrideType
    value: Any
    created_at: datetime
    note: str = ""
    source: OverrideSource = OverrideSource.USER
    active: bool = True
    superseded_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class RejectedMatchDecision:
    rejection_id: str
    tracked_id: str
    scope: RejectionScope
    target: str
    decided_at: datetime
    reason: str = ""
    expires_at: datetime | None = None
    active: bool = True


@dataclass(frozen=True)
class MatchCandidateEvidence:
    candidate_id: str
    path: str
    score: int
    stable_item_id: str = ""
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewCase:
    case_id: str
    tracked_id: str
    status: ReviewStatus
    reason_code: str
    explanation: str
    blocking: bool = True
    active: bool = True
    opened_at: datetime | None = None
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class DecisionReason:
    code: str
    message: str
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DomainWarning:
    code: str
    message: str


@dataclass(frozen=True)
class StatusDecisionInput:
    identity: AniListMediaIdentity
    server: ServerPresenceState
    review_cases: tuple[ReviewCase, ...] = ()
    overrides: tuple[ManualOverride, ...] = ()
    archived: bool = False
    movie_theatrical_released: bool = False
    movie_digital_available: bool = False
    decided_at: datetime | None = None


@dataclass(frozen=True)
class StatusDecision:
    workflow_status: TrackerWorkflowStatus
    anilist_status: AniListStatus
    server_presence: ServerPresence
    review_status: ReviewStatus
    explanation_code: str
    reasons: tuple[DecisionReason, ...] = ()
    warnings: tuple[DomainWarning, ...] = ()
    override_changed_outcome: bool = False
    applied_override_ids: tuple[str, ...] = ()
    aired_episode_count: int | None = None
    mapping_fingerprint: str = ""


@dataclass(frozen=True)
class StatusTransition:
    event_type: TransitionEventType
    anilist_id: int
    previous_workflow: TrackerWorkflowStatus | None
    new_workflow: TrackerWorkflowStatus
    previous_server_presence: ServerPresence | None
    new_server_presence: ServerPresence
    previous_review_status: ReviewStatus | None
    new_review_status: ReviewStatus
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ArchiveBundle:
    tracked_media: TrackedMedia
    mappings: tuple[MediaServerMapping, ...] = ()
    rejections: tuple[RejectedMatchDecision, ...] = ()
    status_history: tuple[StatusTransition, ...] = ()
    notification_history: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchivedTrackedMedia:
    bundle: ArchiveBundle
    archived_at: datetime
    reason: str = ""


@dataclass(frozen=True)
class LegacyAdaptation:
    tracked_media: TrackedMedia
    decision_input: StatusDecisionInput
    review_cases: tuple[ReviewCase, ...] = ()
    warnings: tuple[DomainWarning, ...] = ()


@dataclass(frozen=True)
class ArchivedLegacyRecord:
    source_table: str
    source_key: str
    legacy_anilist_id: int | None
    reason: str
    payload_json: str
    requires_manual_review: bool = True


def replace_state(media: TrackedMedia, state: TrackingState) -> TrackedMedia:
    return replace(media, state=state)
