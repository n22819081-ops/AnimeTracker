from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ...domain.enums import LibraryKind, ServerPresence, TrackingContentKind
from ...domain.models import EpisodeCoverage


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class MappingTargetType(StringEnum):
    SERIES_FOLDER = "SERIES_FOLDER"
    SERIES_SEASON = "SERIES_SEASON"
    SERIES_SPECIALS = "SERIES_SPECIALS"
    MOVIE_ITEM = "MOVIE_ITEM"
    SEPARATE_SERIES = "SEPARATE_SERIES"
    UNKNOWN_TARGET = "UNKNOWN_TARGET"
    NO_SERVER_MAPPING = "NO_SERVER_MAPPING"


class MappingSource(StringEnum):
    AUTOMATIC_SUGGESTION = "AUTOMATIC_SUGGESTION"
    MANUAL_CONFIRMATION = "MANUAL_CONFIRMATION"
    LEGACY_IMPORT = "LEGACY_IMPORT"
    JELLYFIN_API = "JELLYFIN_API"
    FILESYSTEM_INVENTORY = "FILESYSTEM_INVENTORY"
    MIGRATION_REVIEW = "MIGRATION_REVIEW"


class ConfirmationState(StringEnum):
    SUGGESTED = "SUGGESTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    BROKEN = "BROKEN"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class MatchConfidence(StringEnum):
    VERY_STRONG = "VERY_STRONG"
    STRONG = "STRONG"
    POSSIBLE = "POSSIBLE"
    WEAK = "WEAK"
    CONFLICTING = "CONFLICTING"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class PathState(StringEnum):
    EXISTS = "EXISTS"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


class MatchingRejectionScope(StringEnum):
    CANDIDATE = "CANDIDATE"
    EXACT_TARGET = "EXACT_TARGET"
    EXACT_PATH = "EXACT_PATH"
    FOLDER = "FOLDER"
    STABLE_INVENTORY_ITEM = "STABLE_INVENTORY_ITEM"
    SUPPRESS_AUTOMATIC_MATCHING = "SUPPRESS_AUTOMATIC_MATCHING"
    FRANCHISE = "FRANCHISE"


class MatchingReviewType(StringEnum):
    AMBIGUOUS_STRONG_CANDIDATES = "AMBIGUOUS_STRONG_CANDIDATES"
    CONFLICTING_CONFIRMED_MAPPINGS = "CONFLICTING_CONFIRMED_MAPPINGS"
    MISSING_CONFIRMED_PATH = "MISSING_CONFIRMED_PATH"
    MISSING_CONFIRMED_SEASON = "MISSING_CONFIRMED_SEASON"
    MOVIE_SERIES_CONFLICT = "MOVIE_SERIES_CONFLICT"
    SPECIAL_PARENT_UNRESOLVED = "SPECIAL_PARENT_UNRESOLVED"
    DUPLICATE_SEASON_CLAIM = "DUPLICATE_SEASON_CLAIM"
    CONFLICTING_ACTIVE_MAPPINGS = "CONFLICTING_ACTIVE_MAPPINGS"
    ABSOLUTE_NUMBERING_UNRESOLVED = "ABSOLUTE_NUMBERING_UNRESOLVED"
    LEGACY_SEASON_SCOPE_UNKNOWN = "LEGACY_SEASON_SCOPE_UNKNOWN"
    INVENTORY_IDENTITY_CHANGED = "INVENTORY_IDENTITY_CHANGED"
    UNSTABLE_REJECTED_TARGET = "UNSTABLE_REJECTED_TARGET"


class ReviewCaseState(StringEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    SUPERSEDED = "SUPERSEDED"


class ReviewSeverity(StringEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class ManualDecisionType(StringEnum):
    NOT_ON_SERVER = "NOT_ON_SERVER"
    NO_VALID_CANDIDATE = "NO_VALID_CANDIDATE"
    SKIP_FOR_NOW = "SKIP_FOR_NOW"
    CLEAR_CONFIRMED_MAPPING = "CLEAR_CONFIRMED_MAPPING"


@dataclass(frozen=True)
class MappingTarget:
    target_type: MappingTargetType
    library_kind: LibraryKind
    root_identifier: str = ""
    relative_path: str = ""
    normalized_path: str = ""
    inventory_item_id: str = ""
    season_number: int | None = None
    content_kind: TrackingContentKind = TrackingContentKind.UNKNOWN
    inventory_snapshot_id: str = ""
    display_name: str = ""
    path_state: PathState = PathState.UNKNOWN
    evidence_summary: tuple[str, ...] = ()

    @property
    def identity_key(self) -> str:
        return "|".join((
            self.inventory_item_id,
            self.target_type.value,
            str(self.season_number) if self.season_number is not None else "",
            self.normalized_path,
            self.library_kind.value,
        ))

    @property
    def folder_identity_key(self) -> str:
        return self.inventory_item_id or self.normalized_path


@dataclass(frozen=True)
class CandidateEvidence:
    normalized_title_variants: tuple[str, ...] = ()
    provider_format: str = ""
    provider_year: int | None = None
    expected_episode_count: int | None = None
    title_similarity: int = 0
    exact_title_variant: bool = False
    matched_title: str = ""
    year_agreement: bool = False
    year_conflict: bool = False
    library_kind_agreement: bool = False
    media_kind_agreement: bool = False
    season_evidence: bool = False
    season_conflict: bool = False
    episode_count_plausible: bool = False
    episode_range: tuple[int, int] | None = None
    season_zero_evidence: bool = False
    movie_evidence: bool = False
    franchise_relation_evidence: bool = False
    existing_confirmed_mapping: bool = False
    rejection_effect: bool = False
    path_exists: bool | None = None
    absolute_numbering: bool = False
    mixed_folder_warning: bool = False
    warnings: tuple[str, ...] = ()
    score_components: tuple[tuple[str, int], ...] = ()

    @property
    def score(self) -> int:
        return sum(value for _, value in self.score_components)


@dataclass(frozen=True)
class MatchCandidate:
    candidate_id: str
    session_id: str
    anilist_id: int
    target: MappingTarget
    evidence: CandidateEvidence
    confidence: MatchConfidence
    score: int
    preselected: bool = False
    stale: bool = False
    suggested_next_action: str = "Review candidate"


@dataclass(frozen=True)
class MatchingSession:
    session_id: str
    profile_id: str
    inventory_snapshot_id: str
    anilist_version: str
    started_at: datetime
    completed_at: datetime | None = None
    candidate_count: int = 0
    warning_count: int = 0
    canceled: bool = False
    partial: bool = False


@dataclass(frozen=True)
class CandidateGenerationResult:
    session: MatchingSession
    candidates: tuple[MatchCandidate, ...]
    normalized_title_variants: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    suppressed: bool = False


@dataclass(frozen=True)
class PersistentMapping:
    mapping_id: str
    profile_id: str
    anilist_id: int
    target: MappingTarget
    source: MappingSource
    confirmation_state: ConfirmationState
    confidence: MatchConfidence
    created_at: datetime
    updated_at: datetime
    superseded_at: datetime | None = None
    active: bool = True
    user_note: str = ""
    evidence_snapshot_reference: str = ""

    @property
    def is_confirmed(self) -> bool:
        return self.active and self.confirmation_state == ConfirmationState.CONFIRMED


@dataclass(frozen=True)
class MatchingRejection:
    rejection_id: str
    profile_id: str
    anilist_id: int
    scope: MatchingRejectionScope
    target_identity: str
    reason: str
    created_at: datetime
    expires_at: datetime | None = None
    active: bool = True
    cleared_at: datetime | None = None
    source: MappingSource = MappingSource.MANUAL_CONFIRMATION
    target_normalized_path: str = ""


@dataclass(frozen=True)
class AutoMatchSuppression:
    profile_id: str
    anilist_id: int
    active: bool
    created_at: datetime
    cleared_at: datetime | None = None
    reason: str = ""


@dataclass(frozen=True)
class MatchingReviewCase:
    review_id: str
    profile_id: str
    anilist_id: int
    review_type: MatchingReviewType
    state: ReviewCaseState
    severity: ReviewSeverity
    evidence: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    related_mapping_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    resolution: str = ""
    user_note: str = ""


@dataclass(frozen=True)
class MappingCoverageEvaluation:
    mapping: PersistentMapping
    server_presence: ServerPresence
    coverage: EpisodeCoverage | None
    review_cases: tuple[MatchingReviewCase, ...] = ()
    warnings: tuple[str, ...] = ()


class StaleCandidateError(RuntimeError):
    pass


class MappingConflictError(RuntimeError):
    pass
