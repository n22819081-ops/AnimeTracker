from __future__ import annotations

from .enums import ReviewStatus, ServerPresence, TrackerWorkflowStatus, TransitionEventType
from .models import StatusDecision, StatusTransition


def _event(event_type: TransitionEventType, anilist_id: int, old: StatusDecision | None, new: StatusDecision, **details: object) -> StatusTransition:
    return StatusTransition(
        event_type=event_type,
        anilist_id=anilist_id,
        previous_workflow=old.workflow_status if old else None,
        new_workflow=new.workflow_status,
        previous_server_presence=old.server_presence if old else None,
        new_server_presence=new.server_presence,
        previous_review_status=old.review_status if old else None,
        new_review_status=new.review_status,
        details=tuple(sorted((key, str(value)) for key, value in details.items())),
    )


def compare_status_decisions(anilist_id: int, previous: StatusDecision | None, current: StatusDecision) -> tuple[StatusTransition, ...]:
    if previous is None:
        return (_event(TransitionEventType.TRACKING_STARTED, anilist_id, None, current),)
    events: list[StatusTransition] = []
    if previous.workflow_status != current.workflow_status:
        workflow_events = {
            TrackerWorkflowStatus.UPCOMING: TransitionEventType.MOVED_TO_UPCOMING,
            TrackerWorkflowStatus.CURRENTLY_AIRING: TransitionEventType.STARTED_AIRING,
            TrackerWorkflowStatus.MOVIE_THEATRICAL_ONLY: TransitionEventType.MOVIE_BECAME_THEATRICAL,
            TrackerWorkflowStatus.MOVIE_DIGITALLY_AVAILABLE: TransitionEventType.MOVIE_BECAME_DIGITAL,
            TrackerWorkflowStatus.ARCHIVED: TransitionEventType.ARCHIVED,
        }
        event_type = workflow_events.get(current.workflow_status)
        if (
            event_type not in {TransitionEventType.MOVIE_BECAME_THEATRICAL, TransitionEventType.MOVIE_BECAME_DIGITAL}
            and current.anilist_status.value == "FINISHED"
            and previous.anilist_status.value != "FINISHED"
        ):
            event_type = TransitionEventType.SERIES_FINISHED
        elif previous.workflow_status == TrackerWorkflowStatus.ARCHIVED and current.workflow_status != TrackerWorkflowStatus.ARCHIVED:
            event_type = TransitionEventType.RESTORED
        if event_type:
            events.append(_event(event_type, anilist_id, previous, current))
    if previous.aired_episode_count is not None and current.aired_episode_count is not None and current.aired_episode_count > previous.aired_episode_count:
        events.append(_event(TransitionEventType.NEW_EPISODE_AIRED, anilist_id, previous, current, previous=previous.aired_episode_count, current=current.aired_episode_count))
    if previous.server_presence != current.server_presence:
        if current.server_presence == ServerPresence.COMPLETE:
            events.append(_event(TransitionEventType.COVERAGE_BECAME_COMPLETE, anilist_id, previous, current))
            if previous.server_presence in {ServerPresence.NOT_FOUND, ServerPresence.UNKNOWN_COVERAGE}:
                events.append(_event(TransitionEventType.FOUND_ON_SERVER, anilist_id, previous, current))
        elif current.server_presence == ServerPresence.PARTIAL:
            event_type = TransitionEventType.COVERAGE_LOST if previous.server_presence == ServerPresence.COMPLETE else TransitionEventType.COVERAGE_BECAME_PARTIAL
            events.append(_event(event_type, anilist_id, previous, current))
        elif current.server_presence in {ServerPresence.NOT_FOUND, ServerPresence.PATH_MISSING} and previous.server_presence in {ServerPresence.COMPLETE, ServerPresence.PARTIAL}:
            events.append(_event(TransitionEventType.NO_LONGER_FOUND_ON_SERVER, anilist_id, previous, current))
    if previous.mapping_fingerprint != current.mapping_fingerprint:
        events.append(_event(TransitionEventType.MAPPING_CHANGED, anilist_id, previous, current, previous=previous.mapping_fingerprint, current=current.mapping_fingerprint))
    if previous.review_status == ReviewStatus.NONE and current.review_status != ReviewStatus.NONE:
        events.append(_event(TransitionEventType.REVIEW_REQUIRED, anilist_id, previous, current))
    elif previous.review_status != ReviewStatus.NONE and current.review_status == ReviewStatus.NONE:
        events.append(_event(TransitionEventType.REVIEW_RESOLVED, anilist_id, previous, current))
    return tuple(dict.fromkeys(events))
