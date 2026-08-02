from __future__ import annotations

import json
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Iterable

from ...domain.enums import ServerPresence
from ..anilist.models import AniListMedia, AniListRelation
from ..server_inventory.models import RootScanStatus, ServerInventorySnapshot
from .candidates import generate_match_candidates, inventory_snapshot_id, media_version
from .coverage import evaluate_mapping_coverage
from .models import (
    AutoMatchSuppression,
    CandidateGenerationResult,
    ConfirmationState,
    ManualDecisionType,
    MappingCoverageEvaluation,
    MappingSource,
    MappingTarget,
    MatchCandidate,
    MatchConfidence,
    MatchingRejection,
    MatchingRejectionScope,
    MatchingReviewCase,
    MatchingReviewType,
    MatchingSession,
    PersistentMapping,
    ReviewCaseState,
    StaleCandidateError,
)
from .repository import MatchingRepository
from .reviews import addressed_review_types_for_target, generate_matching_reviews


class MatchingService:
    def __init__(self, repository: MatchingRepository, *, clock=None) -> None:
        self.repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def generate_candidates(
        self,
        media: AniListMedia,
        inventory: ServerInventorySnapshot,
        *,
        relations: Iterable[AniListRelation] = (),
        profile_id: str = "default",
        session_id: str | None = None,
        franchise_identity: str = "",
        archived: bool = False,
    ) -> CandidateGenerationResult:
        now = self._clock()
        snapshot_key = inventory_snapshot_id(inventory)
        version = media_version(media)
        partial = any(root.status in {RootScanStatus.PARTIAL, RootScanStatus.INACCESSIBLE, RootScanStatus.MISSING} for root in inventory.roots)
        session = MatchingSession(
            session_id or f"matching-{uuid.uuid4().hex}", profile_id, snapshot_key, version,
            now, now, partial=partial, canceled=inventory.canceled,
        )
        if archived:
            result = CandidateGenerationResult(session, (), (), ("Archived entries are excluded from matching.",), False)
            self.repository.save_session(session)
            return result
        suppression = self.repository.get_suppression(profile_id, media.anilist_id)
        if suppression and suppression.active:
            result = CandidateGenerationResult(session, (), (), ("Automatic matching is suppressed by an explicit user decision.",), True)
            self.repository.save_session(session)
            return result

        rejections = self.repository.list_rejections(profile_id, media.anilist_id, now)
        mappings = self.repository.list_all_active_mappings(profile_id)
        result = generate_match_candidates(
            media, inventory, session, rejections=rejections, mappings=mappings, relations=relations,
            franchise_identity=franchise_identity,
        )
        manual_decision = self.repository.active_manual_decision(profile_id, media.anilist_id)
        if manual_decision is not None:
            candidates = tuple(replace(candidate, preselected=False) for candidate in result.candidates)
            result = replace(
                result,
                candidates=candidates,
                warnings=(*result.warnings, f"Manual decision {manual_decision.value} prevents automatic preselection."),
            )
        result = replace(result, session=replace(
            result.session,
            completed_at=now,
            candidate_count=len(result.candidates),
            warning_count=len(result.warnings) + sum(len(item.evidence.warnings) for item in result.candidates),
        ))
        self.repository.save_session(result.session)
        self.repository.save_candidates(result.candidates)

        reviews = generate_matching_reviews(
            profile_id=profile_id,
            media=media,
            generated=result,
            mappings=mappings,
            now=now,
        )
        for review in reviews:
            self.repository.save_review(review)
        return result

    def get_candidate_details(self, candidate_id: str) -> MatchCandidate:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        return candidate

    def confirm_mapping(
        self,
        candidate_id: str,
        media: AniListMedia,
        inventory: ServerInventorySnapshot,
        *,
        profile_id: str = "default",
        user_note: str = "",
    ) -> PersistentMapping:
        candidate = self.get_candidate_details(candidate_id)
        if candidate.anilist_id != media.anilist_id:
            raise ValueError("Candidate AniList identity does not match the requested media.")
        if candidate.confidence in {MatchConfidence.REJECTED, MatchConfidence.CONFLICTING, MatchConfidence.INSUFFICIENT_EVIDENCE}:
            raise ValueError("Candidate cannot be confirmed in its current evidence state.")
        now = self._clock()
        target = replace(candidate.target, inventory_snapshot_id=inventory_snapshot_id(inventory))
        mapping = PersistentMapping(
            f"mapping-{uuid.uuid4().hex}", profile_id, media.anilist_id, target,
            MappingSource.MANUAL_CONFIRMATION, ConfirmationState.CONFIRMED, candidate.confidence,
            now, now, user_note=user_note, evidence_snapshot_reference=candidate.session_id,
        )
        return self.repository.confirm_candidate(
            candidate_id,
            mapping,
            expected_snapshot_id=inventory_snapshot_id(inventory),
            expected_anilist_version=media_version(media),
            resolve_types=addressed_review_types_for_target(target.target_type.value),
        )

    def create_manual_mapping(
        self,
        anilist_id: int,
        target: MappingTarget,
        *,
        profile_id: str = "default",
        user_note: str = "",
        confidence: MatchConfidence = MatchConfidence.VERY_STRONG,
    ) -> PersistentMapping:
        now = self._clock()
        mapping = PersistentMapping(
            f"mapping-{uuid.uuid4().hex}", profile_id, anilist_id, target,
            MappingSource.MANUAL_CONFIRMATION, ConfirmationState.CONFIRMED, confidence,
            now, now, user_note=user_note, evidence_snapshot_reference=target.inventory_snapshot_id,
        )
        self.repository.replace_with_confirmed_mapping(mapping, reason="MANUAL_CONFIRMATION")
        return mapping

    def reject_candidate(
        self,
        candidate_id: str,
        scope: MatchingRejectionScope,
        *,
        reason: str = "",
        expires_at: datetime | None = None,
        profile_id: str = "default",
        franchise_identity: str = "",
    ) -> MatchingRejection:
        candidate = self.get_candidate_details(candidate_id)
        target = candidate.target
        if scope in {MatchingRejectionScope.CANDIDATE, MatchingRejectionScope.EXACT_TARGET}:
            identity = target.identity_key
        elif scope == MatchingRejectionScope.EXACT_PATH:
            identity = target.normalized_path
        elif scope == MatchingRejectionScope.FOLDER:
            identity = target.folder_identity_key
        elif scope == MatchingRejectionScope.STABLE_INVENTORY_ITEM:
            identity = target.inventory_item_id
        elif scope == MatchingRejectionScope.FRANCHISE:
            if not franchise_identity:
                raise ValueError("Franchise rejection requires an explicit franchise identity.")
            identity = franchise_identity
        else:
            identity = str(candidate.anilist_id)
        rejection = MatchingRejection(
            f"rejection-{uuid.uuid4().hex}", profile_id, candidate.anilist_id, scope,
            identity, reason, self._clock(), expires_at,
        )
        self.repository.save_rejection(rejection, {
            "target_identity_key": target.identity_key,
            "inventory_item_id": target.inventory_item_id,
            "season_number": target.season_number,
            "normalized_path": target.normalized_path,
        })
        return rejection

    def clear_rejection(self, rejection_id: str) -> None:
        self.repository.clear_rejection(rejection_id, self._clock())

    def mark_not_on_server(self, anilist_id: int, *, profile_id: str = "default", reason: str = "") -> None:
        self.repository.save_manual_decision(
            f"override-{uuid.uuid4().hex}", profile_id, anilist_id,
            ManualDecisionType.NOT_ON_SERVER, reason, self._clock(), clear_mappings=True,
        )

    def mark_no_valid_candidate(self, anilist_id: int, *, profile_id: str = "default", reason: str = "") -> None:
        self.repository.save_manual_decision(
            f"override-{uuid.uuid4().hex}", profile_id, anilist_id,
            ManualDecisionType.NO_VALID_CANDIDATE, reason, self._clock(), clear_mappings=False,
        )

    def skip_matching_for_now(self, anilist_id: int, *, profile_id: str = "default", reason: str = "") -> None:
        self.repository.save_manual_decision(
            f"override-{uuid.uuid4().hex}", profile_id, anilist_id,
            ManualDecisionType.SKIP_FOR_NOW, reason, self._clock(), clear_mappings=False,
        )

    def suppress_auto_match(self, anilist_id: int, *, profile_id: str = "default", reason: str = "") -> None:
        self.repository.set_suppression(AutoMatchSuppression(profile_id, anilist_id, True, self._clock(), reason=reason))

    def restore_auto_match(self, anilist_id: int, *, profile_id: str = "default") -> None:
        now = self._clock()
        self.repository.set_suppression(AutoMatchSuppression(profile_id, anilist_id, False, now, now))

    def clear_mapping(self, mapping_id: str) -> None:
        mapping = self.repository.get_mapping(mapping_id)
        if mapping is None:
            raise KeyError(mapping_id)
        now = self._clock()
        self.repository.clear_mapping(mapping_id, now)
        self.repository.save_manual_decision(
            f"override-{uuid.uuid4().hex}", mapping.profile_id, mapping.anilist_id,
            ManualDecisionType.CLEAR_CONFIRMED_MAPPING, "Confirmed mapping cleared.", now,
        )

    def acknowledge_review(self, review_id: str, *, profile_id: str = "default", user_note: str = "") -> None:
        self.repository.resolve_review(
            review_id, profile_id, ReviewCaseState.ACKNOWLEDGED, "Acknowledged", user_note, self._clock(),
        )

    def supersede_review(self, review_id: str, *, profile_id: str = "default", resolution: str = "") -> None:
        self.repository.resolve_review(
            review_id, profile_id, ReviewCaseState.SUPERSEDED, resolution, "", self._clock(),
        )

    def supersede_mapping(self, old_mapping_id: str, replacement: PersistentMapping) -> None:
        self.repository.supersede_mapping(old_mapping_id, replacement)

    def list_open_reviews(self, *, profile_id: str = "default") -> tuple[MatchingReviewCase, ...]:
        return self.repository.list_reviews(profile_id)

    def resolve_review(
        self,
        review_id: str,
        resolution: str,
        *,
        profile_id: str = "default",
        user_note: str = "",
        dismiss: bool = False,
    ) -> None:
        self.repository.resolve_review(
            review_id,
            profile_id,
            ReviewCaseState.DISMISSED if dismiss else ReviewCaseState.RESOLVED,
            resolution,
            user_note,
            self._clock(),
        )

    def get_mapping_history(self, anilist_id: int, *, profile_id: str = "default"):
        return self.repository.get_mapping_history(profile_id, anilist_id)

    def check_confirmed_mappings(
        self,
        media: AniListMedia,
        inventory: ServerInventorySnapshot,
        *,
        aired_episode_count: int | None,
        profile_id: str = "default",
    ) -> tuple[MappingCoverageEvaluation, ...]:
        now = self._clock()
        mappings = self.repository.list_mappings(profile_id, media.anilist_id)
        results = []
        for mapping in mappings:
            evaluation = evaluate_mapping_coverage(
                mapping, media, inventory, aired_episode_count=aired_episode_count, now=now,
            )
            results.append(evaluation)
            if evaluation.server_presence == ServerPresence.PATH_MISSING:
                reason = evaluation.review_cases[0].review_type.value if evaluation.review_cases else "MISSING"
                self.repository.mark_mapping_broken(mapping.mapping_id, now, reason)
            else:
                self.repository.mark_mapping_healthy(mapping.mapping_id, now)
            for review in evaluation.review_cases:
                self.repository.save_review(review)
            self.repository.save_coverage_snapshot(
                mapping.mapping_id,
                inventory_snapshot_id(inventory),
                evaluation.server_presence.value,
                _coverage_json(evaluation),
                now,
            )
        return tuple(results)

    def candidate_diagnostics(self, candidate_id: str) -> dict:
        candidate = self.get_candidate_details(candidate_id)
        session = self.repository.get_session(candidate.session_id)
        return {
            "candidate_id": candidate.candidate_id,
            "session_id": candidate.session_id,
            "inventory_snapshot_id": session.inventory_snapshot_id if session else "",
            "anilist_id": candidate.anilist_id,
            "target": {
                "type": candidate.target.target_type.value,
                "root": candidate.target.root_identifier,
                "relative_path": candidate.target.relative_path,
                "season_number": candidate.target.season_number,
                "inventory_item_id": candidate.target.inventory_item_id,
            },
            "score": candidate.score,
            "confidence": candidate.confidence.value,
            "score_components": candidate.evidence.score_components,
            "normalized_title_variants": candidate.evidence.normalized_title_variants,
            "provider_inputs": {
                "format": candidate.evidence.provider_format,
                "year": candidate.evidence.provider_year,
                "expected_episode_count": candidate.evidence.expected_episode_count,
            },
            "inventory_evidence": candidate.target.evidence_summary,
            "relation_evidence": candidate.evidence.franchise_relation_evidence,
            "rejection_effect": candidate.evidence.rejection_effect,
            "mapping_history_count": len(
                self.repository.get_mapping_history(session.profile_id if session else "default", candidate.anilist_id)
            ),
            "warnings": candidate.evidence.warnings,
            "stale": candidate.stale,
            "suggested_next_action": candidate.suggested_next_action,
        }


def _coverage_json(evaluation: MappingCoverageEvaluation) -> str:
    if evaluation.coverage is None:
        return "{}"
    coverage = evaluation.coverage
    value = asdict(coverage)
    for key, item in tuple(value.items()):
        if isinstance(item, (set, frozenset)):
            value[key] = sorted(item)
        elif hasattr(item, "value"):
            value[key] = item.value
        elif isinstance(item, datetime):
            value[key] = item.isoformat()
    return json.dumps(value, sort_keys=True)
