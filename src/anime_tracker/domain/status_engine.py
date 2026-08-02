from __future__ import annotations

from .enums import AniListStatus, MediaKind, OverrideType, ReviewStatus, ServerPresence, TrackerWorkflowStatus
from .models import DecisionReason, DomainWarning, StatusDecision, StatusDecisionInput
from .overrides import active_overrides, last_override, parse_presence_override, parse_workflow_override


def _reason(code: str, message: str, **details: object) -> DecisionReason:
    return DecisionReason(code, message, tuple(sorted((key, str(value)) for key, value in details.items())))


def _computed_workflow(data: StatusDecisionInput, presence: ServerPresence) -> tuple[TrackerWorkflowStatus, str, list[DecisionReason], list[DomainWarning]]:
    identity = data.identity
    coverage = data.server.coverage
    reasons = [_reason("ANILIST_STATUS", f"AniList status is {identity.status.value}.")]
    warnings = [DomainWarning("COVERAGE_WARNING", warning) for warning in data.server.warnings]
    active_cases = tuple(case for case in data.review_cases if case.active)
    blocking = tuple(case for case in active_cases if case.blocking)
    if data.archived:
        return TrackerWorkflowStatus.ARCHIVED, "ARCHIVED", reasons + [_reason("ARCHIVED", "The title is archived.")], warnings
    if blocking:
        reasons.extend(_reason(case.reason_code, case.explanation) for case in blocking)
        return TrackerWorkflowStatus.NEEDS_REVIEW, "BLOCKING_REVIEW", reasons, warnings
    if presence == ServerPresence.COMPLETE:
        if coverage:
            reasons.append(_reason("SERVER_COVERAGE_COMPLETE", "Required episode coverage is complete.", present=len(coverage.present_episode_numbers)))
        else:
            reasons.append(_reason("SERVER_ITEM_COMPLETE", "A confirmed complete server item is present."))
        return TrackerWorkflowStatus.ON_SERVER, "SERVER_COMPLETE", reasons, warnings
    if identity.media_kind == MediaKind.MOVIE and data.movie_digital_available:
        reasons.append(_reason("MOVIE_DIGITAL", "Digital or Blu-ray availability is confirmed."))
        return TrackerWorkflowStatus.MOVIE_DIGITALLY_AVAILABLE, "MOVIE_DIGITALLY_AVAILABLE", reasons, warnings
    if identity.media_kind == MediaKind.MOVIE and data.movie_theatrical_released:
        reasons.append(_reason("MOVIE_THEATRICAL", "The movie has a theatrical release but no confirmed digital release."))
        return TrackerWorkflowStatus.MOVIE_THEATRICAL_ONLY, "MOVIE_THEATRICAL_ONLY", reasons, warnings
    if identity.status == AniListStatus.NOT_YET_RELEASED:
        return TrackerWorkflowStatus.UPCOMING, "ANILIST_NOT_YET_RELEASED", reasons, warnings
    if identity.status in {AniListStatus.RELEASING, AniListStatus.HIATUS}:
        if coverage:
            reasons.append(_reason(
                "AIRED_COVERAGE",
                "Coverage was evaluated against aired episodes only.",
                aired=coverage.aired_episode_count,
                present=len(coverage.present_episode_numbers),
                missing=",".join(map(str, sorted(coverage.missing_aired_episode_numbers))),
            ))
        return TrackerWorkflowStatus.CURRENTLY_AIRING, "ANILIST_RELEASING", reasons, warnings
    if identity.status == AniListStatus.FINISHED:
        if coverage:
            reasons.append(_reason(
                "EXPECTED_COVERAGE",
                "Coverage was evaluated against the expected finished total.",
                expected=coverage.expected_total_episodes,
                present=len(coverage.present_episode_numbers),
                missing=",".join(map(str, sorted(coverage.missing_expected_episode_numbers))),
            ))
        return TrackerWorkflowStatus.FINISHED_READY_TO_ADD, "ANILIST_FINISHED_INCOMPLETE", reasons, warnings
    warnings.append(DomainWarning("UNKNOWN_OR_INCONSISTENT_STATUS", "No exact workflow rule matched; the title remains upcoming."))
    return TrackerWorkflowStatus.UPCOMING, "DETERMINISTIC_FALLBACK", reasons, warnings


def decide_status(data: StatusDecisionInput) -> StatusDecision:
    overrides = active_overrides(data.overrides, data.decided_at)
    presence = data.server.presence
    presence_override = last_override(overrides, OverrideType.FORCE_SERVER_PRESENCE)
    parsed_presence = parse_presence_override(presence_override.value) if presence_override else None
    if parsed_presence is not None:
        presence = parsed_presence

    computed, code, reasons, warnings = _computed_workflow(data, presence)
    workflow = computed
    applied: list[str] = []
    if presence_override and parsed_presence is not None:
        applied.append(presence_override.override_id)
        reasons.append(_reason("SERVER_PRESENCE_OVERRIDE", "A manual override changed server presence.", value=presence.value))

    workflow_override = last_override(overrides, OverrideType.FORCE_WORKFLOW_STATUS)
    parsed_workflow = parse_workflow_override(workflow_override.value) if workflow_override else None
    if workflow_override and parsed_workflow is not None:
        workflow = parsed_workflow
        applied.append(workflow_override.override_id)
        reasons.append(_reason("WORKFLOW_OVERRIDE", "A manual override changed tracker workflow.", value=workflow.value))

    archive_override = last_override(overrides, OverrideType.ARCHIVE_ENTRY)
    restore_override = last_override(overrides, OverrideType.RESTORE_ARCHIVED_ENTRY)
    if archive_override and (not restore_override or archive_override.created_at > restore_override.created_at):
        workflow = TrackerWorkflowStatus.ARCHIVED
        applied.append(archive_override.override_id)
        reasons.append(_reason("ARCHIVE_OVERRIDE", "An active override archives this title."))
    elif restore_override and data.archived:
        restored_input = StatusDecisionInput(
            identity=data.identity,
            server=data.server,
            review_cases=data.review_cases,
            overrides=tuple(item for item in data.overrides if item.override_type not in {OverrideType.ARCHIVE_ENTRY, OverrideType.RESTORE_ARCHIVED_ENTRY}),
            archived=False,
            movie_theatrical_released=data.movie_theatrical_released,
            movie_digital_available=data.movie_digital_available,
            decided_at=data.decided_at,
        )
        restored = decide_status(restored_input)
        workflow = restored.workflow_status
        code = restored.explanation_code
        reasons = list(restored.reasons) + [_reason("RESTORE_OVERRIDE", "An active override restores this title.")]
        warnings = list(restored.warnings)
        applied = list(restored.applied_override_ids) + [restore_override.override_id]

    active_reviews = tuple(sorted((case for case in data.review_cases if case.active), key=lambda case: (not case.blocking, case.status.value, case.case_id)))
    review_status = active_reviews[0].status if active_reviews else ReviewStatus.NONE
    coverage = data.server.coverage
    return StatusDecision(
        workflow_status=workflow,
        anilist_status=data.identity.status,
        server_presence=presence,
        review_status=review_status,
        explanation_code=code,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
        override_changed_outcome=(workflow != computed or presence != data.server.presence),
        applied_override_ids=tuple(dict.fromkeys(applied)),
        aired_episode_count=coverage.aired_episode_count if coverage else None,
    )
