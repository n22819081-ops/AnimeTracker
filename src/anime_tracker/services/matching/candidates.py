from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Mapping

from ...domain.enums import LibraryKind, MediaKind, TrackingContentKind
from ..anilist.models import AniListMedia, AniListRelation
from ..server_inventory.models import InventoryLibraryItem, ServerInventorySnapshot
from .models import (
    CandidateGenerationResult,
    MappingTarget,
    MappingTargetType,
    MatchCandidate,
    MatchConfidence,
    MatchingRejection,
    MatchingRejectionScope,
    MatchingSession,
    PathState,
    PersistentMapping,
)
from .scoring import build_evidence, classify_confidence, explicit_season_number, normalized_variants, title_match


SPECIAL_KINDS = {MediaKind.OVA, MediaKind.ONA, MediaKind.SPECIAL}


def inventory_snapshot_id(snapshot: ServerInventorySnapshot) -> str:
    payload = []
    for root in snapshot.roots:
        payload.append(("root", root.root.label, root.root.library_kind.value, root.status.value))
        for item in root.items:
            payload.append(("item", item.item_id, item.library_kind.value, item.normalized_path))
            for season in item.seasons:
                payload.append(("season", item.item_id, season.season_number))
                for file in season.files:
                    payload.append(("file", file.normalized_path, file.size, file.modified_ns, file.episode_numbers))
            for group in item.specials:
                payload.append(("special", item.item_id, group.kind.value))
                for file in group.files:
                    payload.append(("file", file.normalized_path, file.size, file.modified_ns, file.episode_numbers))
            for file in (*item.movie_files, *item.unrecognized_media):
                payload.append(("file", file.normalized_path, file.size, file.modified_ns, file.absolute_episode_numbers))
    return hashlib.sha256(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def media_version(media: AniListMedia) -> str:
    values = (
        media.anilist_id,
        media.provider_updated_at,
        media.media_format.value,
        media.status.value,
        media.season_year,
        media.episode_count,
        media.title.variants,
    )
    return hashlib.sha256(repr(values).encode("utf-8")).hexdigest()


def generate_match_candidates(
    media: AniListMedia,
    snapshot: ServerInventorySnapshot,
    session: MatchingSession,
    *,
    rejections: Iterable[MatchingRejection] = (),
    mappings: Iterable[PersistentMapping] = (),
    relations: Iterable[AniListRelation] = (),
    franchise_identity: str = "",
) -> CandidateGenerationResult:
    desired_season = explicit_season_number(media)
    mappings = tuple(mappings)
    rejections = tuple(rejections)
    related_ids = _related_ids(media.anilist_id, relations)
    related_item_ids = {
        mapping.target.inventory_item_id
        for mapping in mappings
        if mapping.is_confirmed and mapping.anilist_id in related_ids
    }
    current_active_mappings = tuple(mapping for mapping in mappings if mapping.active and mapping.anilist_id == media.anilist_id)
    current_confirmed_mappings = tuple(
        mapping for mapping in current_active_mappings
        if mapping.confirmation_state.value in {"CONFIRMED", "BROKEN", "NEEDS_REVIEW"}
    )
    candidates: list[MatchCandidate] = []
    warnings: list[str] = []

    for item in snapshot.items:
        target_options = _targets_for_item(media, item, snapshot, desired_season)
        for target in target_options:
            exact_existing = any(mapping.target.identity_key == target.identity_key for mapping in current_confirmed_mappings)
            rejected, unstable_rejection = _rejection_effect(target, rejections, franchise_identity)
            media_kind_agreement = _media_kind_agrees(media, target)
            absolute = any(file.absolute_episode_numbers for file in item.unrecognized_media)
            mixed = len(item.unrecognized_media) > 1
            evidence = build_evidence(
                media,
                item,
                target,
                desired_season=desired_season,
                expected_episode_count=media.episode_count,
                related_mapping=item.item_id in related_item_ids,
                existing_confirmed=exact_existing,
                rejected=rejected,
                mixed_folder=mixed,
                absolute_numbering=absolute,
                media_kind_agreement=media_kind_agreement,
            )
            if unstable_rejection:
                evidence = replace(
                    evidence,
                    warnings=(*evidence.warnings, "A rejected target reappeared with a changed stable inventory identity."),
                )
            if evidence.title_similarity < 45 and not evidence.existing_confirmed_mapping and not evidence.franchise_relation_evidence:
                continue
            score = evidence.score
            confidence = classify_confidence(score, evidence)
            if confidence == MatchConfidence.INSUFFICIENT_EVIDENCE and not exact_existing:
                continue
            candidate_id = _candidate_id(session.session_id, target.identity_key)
            candidates.append(MatchCandidate(
                candidate_id,
                session.session_id,
                media.anilist_id,
                replace(target, evidence_summary=_score_reasons(evidence)),
                evidence,
                confidence,
                score,
                suggested_next_action="Keep confirmed mapping" if exact_existing else "Review candidate",
            ))

    candidates.sort(key=lambda item: (-item.score, item.target.identity_key, item.candidate_id))
    candidates = _apply_preselection(candidates, bool(current_active_mappings), media.media_format in SPECIAL_KINDS)
    if current_active_mappings and not any(item.evidence.existing_confirmed_mapping for item in candidates):
        warnings.append("The confirmed mapping is not present in this inventory; no replacement will be preselected.")
    if desired_season is None and media.media_format not in {MediaKind.MOVIE, *SPECIAL_KINDS}:
        warnings.append("Season scope is not explicit in AniList title evidence.")
    completed = replace(
        session,
        candidate_count=len(candidates),
        warning_count=len(warnings) + sum(len(item.evidence.warnings) for item in candidates),
    )
    return CandidateGenerationResult(completed, tuple(candidates), normalized_variants(media), tuple(warnings))


def _targets_for_item(
    media: AniListMedia,
    item: InventoryLibraryItem,
    snapshot: ServerInventorySnapshot,
    desired_season: int | None,
) -> tuple[MappingTarget, ...]:
    root_path = next((root.root.path for root in snapshot.roots if root.root.label == item.root_label), "")
    relative = _relative(item.path, root_path)
    common = dict(
        library_kind=item.library_kind,
        root_identifier=item.root_label,
        relative_path=relative,
        normalized_path=item.normalized_path,
        inventory_item_id=item.item_id,
        inventory_snapshot_id=inventory_snapshot_id(snapshot),
        display_name=item.title,
        path_state=PathState.EXISTS,
    )
    if media.media_format == MediaKind.MOVIE:
        if item.library_kind != LibraryKind.MOVIE or not item.movie_files:
            return ()
        return (MappingTarget(MappingTargetType.MOVIE_ITEM, content_kind=TrackingContentKind.MOVIE, **common),)

    if media.media_format in SPECIAL_KINDS:
        options: list[MappingTarget] = []
        if item.library_kind == LibraryKind.TV:
            if item.specials:
                options.append(MappingTarget(
                    MappingTargetType.SERIES_SPECIALS,
                    season_number=0,
                    content_kind=_special_content_kind(media.media_format),
                    **common,
                ))
            similarity, exact, _ = title_match(media, item)
            if (exact or similarity >= 60) and (item.seasons or item.unrecognized_media):
                options.append(MappingTarget(
                    MappingTargetType.SEPARATE_SERIES,
                    content_kind=_special_content_kind(media.media_format),
                    **common,
                ))
        elif item.library_kind == LibraryKind.MOVIE and item.movie_files:
            options.append(MappingTarget(
                MappingTargetType.MOVIE_ITEM,
                content_kind=_special_content_kind(media.media_format),
                **common,
            ))
        return tuple(options)

    if item.library_kind != LibraryKind.TV:
        return ()
    if desired_season is not None:
        if any(season.season_number == desired_season for season in item.seasons):
            return (MappingTarget(
                MappingTargetType.SERIES_SEASON,
                season_number=desired_season,
                content_kind=TrackingContentKind.SEASON,
                **common,
            ),)
        return ()
    ordinary = tuple(season for season in item.seasons if season.season_number > 0)
    if ordinary:
        return tuple(
            MappingTarget(
                MappingTargetType.SERIES_SEASON,
                season_number=season.season_number,
                content_kind=TrackingContentKind.SEASON,
                **common,
            )
            for season in ordinary
        )
    return (MappingTarget(
        MappingTargetType.UNKNOWN_TARGET,
        content_kind=TrackingContentKind.SERIES,
        **common,
    ),)


def _apply_preselection(
    candidates: list[MatchCandidate],
    has_confirmed_mapping: bool,
    special_media: bool,
) -> list[MatchCandidate]:
    if not candidates or has_confirmed_mapping:
        return candidates
    first = candidates[0]
    second_score = candidates[1].score if len(candidates) > 1 else -10_000
    explicit_scope = first.target.target_type in {
        MappingTargetType.SERIES_SEASON,
        MappingTargetType.MOVIE_ITEM,
        MappingTargetType.SEPARATE_SERIES,
    }
    safe = (
        first.confidence in {MatchConfidence.VERY_STRONG, MatchConfidence.STRONG}
        and first.score - second_score >= 20
        and explicit_scope
        and not special_media
        and not first.evidence.rejection_effect
        and not first.evidence.absolute_numbering
        and not first.evidence.mixed_folder_warning
        and not first.evidence.season_conflict
    )
    if not safe:
        return candidates
    return [replace(item, preselected=index == 0) for index, item in enumerate(candidates)]


def _rejection_effect(
    target: MappingTarget,
    rejections: tuple[MatchingRejection, ...],
    franchise_identity: str,
) -> tuple[bool, bool]:
    unstable = False
    for rejection in rejections:
        if rejection.scope in {MatchingRejectionScope.CANDIDATE, MatchingRejectionScope.EXACT_TARGET}:
            if rejection.target_identity == target.identity_key:
                return True, unstable
        elif rejection.scope == MatchingRejectionScope.FOLDER:
            if rejection.target_identity.casefold() in {target.folder_identity_key.casefold(), target.normalized_path.casefold()}:
                return True, unstable
        elif rejection.scope == MatchingRejectionScope.EXACT_PATH:
            if rejection.target_identity.casefold() == target.normalized_path.casefold():
                return True, unstable
        elif rejection.scope == MatchingRejectionScope.STABLE_INVENTORY_ITEM:
            if rejection.target_identity == target.inventory_item_id:
                return True, unstable
            if (
                rejection.target_identity != target.inventory_item_id
                and rejection.target_normalized_path
                and rejection.target_normalized_path.casefold() == target.normalized_path.casefold()
            ):
                unstable = True
        elif rejection.scope == MatchingRejectionScope.FRANCHISE:
            if franchise_identity and rejection.target_identity == franchise_identity:
                return True, unstable
    return False, unstable


def _media_kind_agrees(media: AniListMedia, target: MappingTarget) -> bool:
    if media.media_format == MediaKind.MOVIE:
        return target.target_type == MappingTargetType.MOVIE_ITEM and target.library_kind == LibraryKind.MOVIE
    if media.media_format in SPECIAL_KINDS:
        return target.target_type in {
            MappingTargetType.SERIES_SPECIALS,
            MappingTargetType.SEPARATE_SERIES,
            MappingTargetType.MOVIE_ITEM,
        }
    return target.library_kind == LibraryKind.TV and target.target_type in {
        MappingTargetType.SERIES_FOLDER,
        MappingTargetType.SERIES_SEASON,
        MappingTargetType.UNKNOWN_TARGET,
    }


def _special_content_kind(kind: MediaKind) -> TrackingContentKind:
    return {
        MediaKind.OVA: TrackingContentKind.OVA,
        MediaKind.ONA: TrackingContentKind.ONA,
        MediaKind.SPECIAL: TrackingContentKind.SPECIAL,
    }.get(kind, TrackingContentKind.SPECIAL)


def _related_ids(anilist_id: int, relations: Iterable[AniListRelation]) -> set[int]:
    values: set[int] = set()
    for relation in relations:
        if relation.source_anilist_id == anilist_id and relation.target_anilist_id is not None:
            values.add(int(relation.target_anilist_id))
        elif relation.target_anilist_id == anilist_id:
            values.add(relation.source_anilist_id)
    return values


def _candidate_id(session_id: str, target_identity: str) -> str:
    digest = hashlib.sha256(f"{session_id}|{target_identity}".encode("utf-8")).hexdigest()[:24]
    return f"candidate-{digest}"


def _score_reasons(evidence) -> tuple[str, ...]:
    values = [f"{name}: {value:+d}" for name, value in evidence.score_components]
    values.extend(evidence.warnings)
    return tuple(values)


def _relative(path: str, root: str) -> str:
    if not root:
        return Path(path).name
    try:
        return str(Path(path).relative_to(Path(root)))
    except ValueError:
        return Path(path).name
