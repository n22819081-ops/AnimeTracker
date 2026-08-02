from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ...domain.enums import LibraryKind, TrackingContentKind
from .models import (
    AutoMatchSuppression,
    CandidateEvidence,
    ConfirmationState,
    ManualDecisionType,
    MappingSource,
    MappingTarget,
    MappingTargetType,
    MatchCandidate,
    MatchConfidence,
    MatchingRejection,
    MatchingRejectionScope,
    MatchingReviewCase,
    MatchingReviewType,
    MatchingSession,
    PathState,
    PersistentMapping,
    ReviewCaseState,
    ReviewSeverity,
    StaleCandidateError,
)


class MatchingRepository:
    """Path-only repository; every operation owns its SQLite connection."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_session(self, session: MatchingSession) -> None:
        with self.connect() as connection:
            self._save_session(connection,session)

    @staticmethod
    def _save_session(connection:sqlite3.Connection,session:MatchingSession)->None:
        connection.execute(
                """
                INSERT OR REPLACE INTO matching_sessions(
                    session_id,profile_id,inventory_snapshot_id,anilist_version,started_at,
                    completed_at,candidate_count,warning_count,canceled,partial
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session.session_id, session.profile_id, session.inventory_snapshot_id,
                    session.anilist_version, _iso(session.started_at), _iso(session.completed_at),
                    session.candidate_count, session.warning_count, int(session.canceled), int(session.partial),
                ),
            )

    def save_candidates(self, candidates: tuple[MatchCandidate, ...]) -> None:
        if not candidates:
            return
        with self.connect() as connection:
            self._save_candidates(connection,candidates)

    @staticmethod
    def _save_candidates(connection:sqlite3.Connection,candidates:tuple[MatchCandidate,...])->None:
        for candidate in candidates:
            target = candidate.target
            connection.execute(
                    """
                    INSERT OR REPLACE INTO server_match_candidates(
                        candidate_id,session_id,profile_id,anilist_id,target_identity_key,target_type,
                        inventory_item_id,root_identifier,relative_path,normalized_path,season_number,
                        library_kind,content_kind,inventory_snapshot_id,display_name,path_state,score,
                        confidence,evidence_json,preselected,stale,suggested_next_action,created_at
                    )
                    SELECT ?,?,profile_id,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,started_at
                      FROM matching_sessions WHERE session_id=?
                    """,
                    (
                        candidate.candidate_id, candidate.session_id, candidate.anilist_id,
                        target.identity_key, target.target_type.value, target.inventory_item_id,
                        target.root_identifier, target.relative_path, target.normalized_path,
                        target.season_number, target.library_kind.value, target.content_kind.value,
                        target.inventory_snapshot_id, target.display_name, target.path_state.value,
                        candidate.score, candidate.confidence.value, _evidence_json(candidate.evidence),
                        int(candidate.preselected), int(candidate.stale), candidate.suggested_next_action,
                        candidate.session_id,
                    ),
                )

    def save_generation_batch(self,values)->None:
        """Persist prepared sessions, candidates, and reviews in one thread-owned transaction."""
        with self.connect() as connection:
            for session,candidates,reviews in values:
                self._save_session(connection,session)
                self._save_candidates(connection,candidates)
                for review in reviews:
                    self._save_review(connection,review)

    def get_session(self, session_id: str) -> MatchingSession | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM matching_sessions WHERE session_id=?", (session_id,)).fetchone()
        return _session_from_row(row) if row else None

    def get_candidate(self, candidate_id: str) -> MatchCandidate | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM server_match_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        return _candidate_from_row(row) if row else None

    def get_mapping(self, mapping_id: str) -> PersistentMapping | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM media_server_mappings WHERE mapping_id=?", (mapping_id,)).fetchone()
        return _mapping_from_row(row) if row else None

    def mark_session_candidates_stale(self, session_id: str) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE server_match_candidates SET stale=1 WHERE session_id=?", (session_id,))

    def list_mappings(self, profile_id: str, anilist_id: int, *, include_inactive: bool = False) -> tuple[PersistentMapping, ...]:
        query = "SELECT * FROM media_server_mappings WHERE profile_id=? AND anilist_id=?"
        parameters: tuple[object, ...] = (profile_id, anilist_id)
        if not include_inactive:
            query += " AND active=1"
        query += " ORDER BY created_at,mapping_id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(_mapping_from_row(row) for row in rows)

    def list_all_active_mappings(self, profile_id: str) -> tuple[PersistentMapping, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM media_server_mappings WHERE profile_id=? AND active=1 ORDER BY anilist_id,mapping_id",
                (profile_id,),
            ).fetchall()
        return tuple(_mapping_from_row(row) for row in rows)

    def save_mapping(self, mapping: PersistentMapping, *, event_type: str = "MAPPING_CREATED") -> None:
        with self.connect() as connection:
            self._insert_mapping(connection, mapping)
            self._insert_history(connection, mapping, event_type)

    def replace_with_confirmed_mapping(self, mapping: PersistentMapping, *, reason: str) -> None:
        with self.connect() as connection:
            self._supersede_active(connection, mapping.profile_id, mapping.anilist_id, mapping.created_at, reason)
            self._insert_mapping(connection, mapping)
            self._insert_history(connection, mapping, "MANUAL_MAPPING_CONFIRMED")
            connection.execute(
                "UPDATE mapping_overrides SET active=0,cleared_at=? WHERE profile_id=? AND anilist_id=? AND active=1",
                (_iso(mapping.created_at), mapping.profile_id, mapping.anilist_id),
            )

    def confirm_candidate(
        self,
        candidate_id: str,
        mapping: PersistentMapping,
        *,
        expected_snapshot_id: str,
        expected_anilist_version: str,
        resolve_types: tuple[MatchingReviewType, ...] = (),
    ) -> PersistentMapping:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT c.*,s.inventory_snapshot_id AS session_snapshot,s.anilist_version AS session_anilist_version
                  FROM server_match_candidates c JOIN matching_sessions s ON s.session_id=c.session_id
                 WHERE c.candidate_id=?
                """,
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            if row["stale"] or row["session_snapshot"] != expected_snapshot_id or row["session_anilist_version"] != expected_anilist_version:
                connection.execute("UPDATE server_match_candidates SET stale=1 WHERE candidate_id=?", (candidate_id,))
                raise StaleCandidateError("Candidate evidence is stale; regenerate before confirmation.")
            self._supersede_active(connection, mapping.profile_id, mapping.anilist_id, mapping.updated_at, "EXPLICIT_CONFIRMATION")
            self._insert_mapping(connection, mapping)
            self._insert_history(connection, mapping, "CANDIDATE_CONFIRMED")
            connection.execute(
                """
                INSERT INTO mapping_evidence(mapping_id,evidence_type,evidence_json,inventory_snapshot_id,created_at)
                VALUES(?,?,?,?,?)
                """,
                (mapping.mapping_id, "CONFIRMED_CANDIDATE", row["evidence_json"], expected_snapshot_id, _iso(mapping.created_at)),
            )
            connection.execute(
                "UPDATE mapping_overrides SET active=0,cleared_at=? WHERE profile_id=? AND anilist_id=? AND active=1",
                (_iso(mapping.updated_at), mapping.profile_id, mapping.anilist_id),
            )
            if resolve_types:
                placeholders = ",".join("?" for _ in resolve_types)
                connection.execute(
                    f"""
                    UPDATE review_cases SET state='RESOLVED',resolution='Mapping confirmed',updated_at=?
                     WHERE profile_id=? AND anilist_id=? AND state IN ('OPEN','ACKNOWLEDGED')
                       AND review_type IN ({placeholders})
                    """,
                    (_iso(mapping.updated_at), mapping.profile_id, mapping.anilist_id, *(item.value for item in resolve_types)),
                )
        return mapping

    def supersede_mapping(self, mapping_id: str, replacement: PersistentMapping) -> None:
        with self.connect() as connection:
            old = connection.execute("SELECT * FROM media_server_mappings WHERE mapping_id=?", (mapping_id,)).fetchone()
            if old is None:
                raise KeyError(mapping_id)
            connection.execute(
                "UPDATE media_server_mappings SET active=0,confirmation_state='SUPERSEDED',superseded_at=?,updated_at=? WHERE mapping_id=?",
                (_iso(replacement.created_at), _iso(replacement.created_at), mapping_id),
            )
            self._insert_history(connection, _mapping_from_row(old), "MAPPING_SUPERSEDED")
            self._insert_mapping(connection, replacement)
            self._insert_history(connection, replacement, "MAPPING_CREATED")

    def clear_mapping(self, mapping_id: str, when: datetime) -> None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM media_server_mappings WHERE mapping_id=?", (mapping_id,)).fetchone()
            if row is None:
                raise KeyError(mapping_id)
            mapping = _mapping_from_row(row)
            connection.execute(
                "UPDATE media_server_mappings SET active=0,confirmation_state='SUPERSEDED',superseded_at=?,updated_at=? WHERE mapping_id=?",
                (_iso(when), _iso(when), mapping_id),
            )
            self._insert_history(connection, mapping, "MAPPING_CLEARED", when)

    def mark_mapping_broken(self, mapping_id: str, when: datetime, reason: str) -> None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM media_server_mappings WHERE mapping_id=?", (mapping_id,)).fetchone()
            if row is None:
                raise KeyError(mapping_id)
            mapping = _mapping_from_row(row)
            if row["confirmation_state"] == "BROKEN" and row["path_state"] == "MISSING":
                return
            connection.execute(
                "UPDATE media_server_mappings SET confirmation_state='BROKEN',path_state='MISSING',updated_at=? WHERE mapping_id=?",
                (_iso(when), mapping_id),
            )
            self._insert_history(connection, mapping, f"MAPPING_BROKEN:{reason}", when)

    def mark_mapping_healthy(self, mapping_id: str, when: datetime) -> None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM media_server_mappings WHERE mapping_id=?", (mapping_id,)).fetchone()
            if row is None:
                raise KeyError(mapping_id)
            if row["confirmation_state"] == "BROKEN":
                mapping = _mapping_from_row(row)
                connection.execute(
                    "UPDATE media_server_mappings SET confirmation_state='CONFIRMED',path_state='EXISTS',updated_at=? WHERE mapping_id=?",
                    (_iso(when), mapping_id),
                )
                self._insert_history(connection, mapping, "MAPPING_HEALTH_RESTORED", when)

    def get_mapping_history(self, profile_id: str, anilist_id: int) -> tuple[sqlite3.Row, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT h.* FROM mapping_history h JOIN media_server_mappings m ON m.mapping_id=h.mapping_id
                 WHERE m.profile_id=? AND m.anilist_id=? ORDER BY h.occurred_at,h.history_id
                """,
                (profile_id, anilist_id),
            ).fetchall()
        return tuple(rows)

    def save_rejection(self, rejection: MatchingRejection, target_json: dict | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO rejected_match_decisions(
                    rejection_id,profile_id,anilist_id,scope,target_identity,target_json,reason,
                    created_at,expires_at,active,cleared_at,source
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rejection.rejection_id, rejection.profile_id, rejection.anilist_id,
                    rejection.scope.value, rejection.target_identity,
                    json.dumps(target_json or {}, sort_keys=True), rejection.reason,
                    _iso(rejection.created_at), _iso(rejection.expires_at), int(rejection.active),
                    _iso(rejection.cleared_at), rejection.source.value,
                ),
            )

    def list_rejections(self, profile_id: str, anilist_id: int, at: datetime) -> tuple[MatchingRejection, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM rejected_match_decisions
                 WHERE profile_id=? AND anilist_id=? AND active=1
                   AND (expires_at IS NULL OR expires_at>?) ORDER BY created_at,rejection_id
                """,
                (profile_id, anilist_id, _iso(at)),
            ).fetchall()
        return tuple(_rejection_from_row(row) for row in rows)

    def clear_rejection(self, rejection_id: str, when: datetime) -> None:
        with self.connect() as connection:
            result = connection.execute(
                "UPDATE rejected_match_decisions SET active=0,cleared_at=? WHERE rejection_id=? AND active=1",
                (_iso(when), rejection_id),
            )
            if result.rowcount == 0:
                raise KeyError(rejection_id)

    def set_suppression(self, suppression: AutoMatchSuppression) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO automatic_match_suppressions(profile_id,anilist_id,active,created_at,cleared_at,reason)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(profile_id,anilist_id) DO UPDATE SET
                    active=excluded.active,created_at=excluded.created_at,cleared_at=excluded.cleared_at,reason=excluded.reason
                """,
                (
                    suppression.profile_id, suppression.anilist_id, int(suppression.active),
                    _iso(suppression.created_at), _iso(suppression.cleared_at), suppression.reason,
                ),
            )

    def get_suppression(self, profile_id: str, anilist_id: int) -> AutoMatchSuppression | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM automatic_match_suppressions WHERE profile_id=? AND anilist_id=?",
                (profile_id, anilist_id),
            ).fetchone()
        if row is None:
            return None
        return AutoMatchSuppression(
            row["profile_id"], row["anilist_id"], bool(row["active"]),
            _datetime(row["created_at"]), _datetime(row["cleared_at"]), row["reason"],
        )

    def save_review(self, review: MatchingReviewCase) -> None:
        with self.connect() as connection:
            self._save_review(connection,review)

    @staticmethod
    def _save_review(connection:sqlite3.Connection,review:MatchingReviewCase)->None:
        connection.execute(
                """
                INSERT INTO review_cases(
                    review_id,profile_id,anilist_id,review_type,state,severity,evidence_json,
                    related_mapping_ids_json,created_at,updated_at,resolution,user_note
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(review_id) DO UPDATE SET
                    severity=excluded.severity,evidence_json=excluded.evidence_json,
                    related_mapping_ids_json=excluded.related_mapping_ids_json,updated_at=excluded.updated_at
                """,
                (
                    review.review_id, review.profile_id, review.anilist_id, review.review_type.value,
                    review.state.value, review.severity.value, json.dumps(review.evidence),
                    json.dumps(review.related_mapping_ids), _iso(review.created_at), _iso(review.updated_at),
                    review.resolution, review.user_note,
                ),
            )
        connection.execute("DELETE FROM review_case_candidates WHERE review_id=?", (review.review_id,))
        connection.executemany(
                "INSERT INTO review_case_candidates(review_id,candidate_id) VALUES(?,?)",
                ((review.review_id, candidate_id) for candidate_id in review.candidate_ids),
            )

    def list_reviews(
        self,
        profile_id: str,
        *,
        anilist_id: int | None = None,
        open_only: bool = True,
    ) -> tuple[MatchingReviewCase, ...]:
        query = "SELECT * FROM review_cases WHERE profile_id=?"
        parameters: list[object] = [profile_id]
        if anilist_id is not None:
            query += " AND anilist_id=?"
            parameters.append(anilist_id)
        if open_only:
            query += " AND state IN ('OPEN','ACKNOWLEDGED')"
        query += " ORDER BY created_at,review_id"
        with self.connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
            result = []
            for row in rows:
                candidates = tuple(item[0] for item in connection.execute(
                    "SELECT candidate_id FROM review_case_candidates WHERE review_id=? ORDER BY candidate_id",
                    (row["review_id"],),
                ))
                result.append(_review_from_row(row, candidates))
        return tuple(result)

    def resolve_review(
        self,
        review_id: str,
        profile_id: str,
        state: ReviewCaseState,
        resolution: str,
        user_note: str,
        when: datetime,
    ) -> None:
        if state not in {ReviewCaseState.RESOLVED, ReviewCaseState.DISMISSED, ReviewCaseState.SUPERSEDED, ReviewCaseState.ACKNOWLEDGED}:
            raise ValueError("Review resolution state is invalid.")
        with self.connect() as connection:
            result = connection.execute(
                "UPDATE review_cases SET state=?,resolution=?,user_note=?,updated_at=? WHERE review_id=? AND profile_id=?",
                (state.value, resolution, user_note, _iso(when), review_id, profile_id),
            )
            if result.rowcount == 0:
                raise KeyError(review_id)

    def reconcile_candidate_reviews(
        self,
        profile_id:str,
        anilist_id:int,
        candidate_ids:tuple[str,...],
        when:datetime,
    )->dict[str,int]:
        candidate_types=(
            "AMBIGUOUS_STRONG_CANDIDATES","ABSOLUTE_NUMBERING_UNRESOLVED",
            "UNSTABLE_REJECTED_TARGET","SPECIAL_PARENT_UNRESOLVED",
        )
        placeholders=",".join("?" for _ in candidate_types)
        linked=superseded=0
        with self.connect() as connection:
            rows=connection.execute(
                f"SELECT review_id FROM review_cases WHERE profile_id=? AND anilist_id=? AND state IN ('OPEN','ACKNOWLEDGED') AND review_type IN ({placeholders})",
                (profile_id,anilist_id,*candidate_types),
            ).fetchall()
            for row in rows:
                review_id=row["review_id"]
                if candidate_ids:
                    connection.execute("DELETE FROM review_case_candidates WHERE review_id=?",(review_id,))
                    connection.executemany("INSERT INTO review_case_candidates(review_id,candidate_id) VALUES(?,?)",((review_id,value) for value in candidate_ids[:8]))
                    linked+=1
                else:
                    connection.execute("UPDATE review_cases SET state='SUPERSEDED',resolution='NO_CURRENT_CANDIDATE',user_note='Complete inventory scan found no current candidate; no match is a normal server state.',updated_at=? WHERE review_id=?",(_iso(when),review_id))
                    superseded+=1
        return {"linked":linked,"superseded":superseded}

    def resolve_review_not_on_server(
        self,
        review_id: str,
        profile_id: str,
        anilist_id: int,
        override_id: str,
        reason: str,
        when: datetime,
    ) -> dict[str, object]:
        """Resolve one review and persist an idempotent, candidate-free manual decision."""
        timestamp = _iso(when)
        with self.connect() as connection:
            tracked = connection.execute(
                """
                SELECT tm.id,am.anilist_status,am.media_format,ts.tracker_status
                  FROM tracked_media tm
                  JOIN anilist_media am ON am.anilist_id=tm.anilist_id
                  JOIN tracking_state ts ON ts.tracked_media_id=tm.id
                 WHERE tm.anilist_id=? AND tm.archived_at IS NULL
                """,
                (anilist_id,),
            ).fetchone()
            if tracked is None:
                raise ValueError(f"AniList {anilist_id} is not an active tracked title.")
            review = connection.execute(
                "SELECT state,anilist_id FROM review_cases WHERE review_id=? AND profile_id=?",
                (review_id, profile_id),
            ).fetchone()
            if review is None or int(review["anilist_id"]) != anilist_id:
                raise ValueError("The selected review does not belong to this tracked title and profile.")

            existing = connection.execute(
                """
                SELECT override_id FROM mapping_overrides
                 WHERE profile_id=? AND anilist_id=? AND decision_type='NOT_ON_SERVER' AND active=1
                 ORDER BY created_at DESC LIMIT 1
                """,
                (profile_id, anilist_id),
            ).fetchone()
            decision_created = existing is None
            if decision_created:
                connection.execute(
                    "UPDATE mapping_overrides SET active=0,cleared_at=? WHERE profile_id=? AND anilist_id=? AND active=1",
                    (timestamp, profile_id, anilist_id),
                )
                connection.execute(
                    """
                    INSERT INTO mapping_overrides(
                        override_id,profile_id,anilist_id,decision_type,active,reason,created_at
                    ) VALUES(?,?,?,'NOT_ON_SERVER',1,?,?)
                    """,
                    (override_id, profile_id, anilist_id, reason, timestamp),
                )

            if review["state"] in {"OPEN", "ACKNOWLEDGED"}:
                connection.execute(
                    """
                    UPDATE review_cases
                       SET state='RESOLVED',resolution='MARKED_NOT_ON_SERVER',user_note=?,updated_at=?
                     WHERE review_id=? AND profile_id=?
                    """,
                    (reason, timestamp, review_id, profile_id),
                )

            remaining = connection.execute(
                """
                SELECT review_type,evidence_json FROM review_cases
                 WHERE profile_id=? AND anilist_id=? AND state IN ('OPEN','ACKNOWLEDGED')
                 ORDER BY created_at,review_id
                """,
                (profile_id, anilist_id),
            ).fetchall()
            previous_status = tracked["tracker_status"]
            if remaining:
                tracker_status = "Needs Review"
                server_presence = "NEEDS_REVIEW"
                review_status = "OPEN"
                review_reason = "; ".join(str(row["review_type"]).replace("_", " ").title() for row in remaining)
            else:
                tracker_status = _anilist_tracker_status(
                    tracked["anilist_status"], tracked["media_format"], previous_status,
                )
                server_presence = "NOT_ON_SERVER"
                review_status = "NONE"
                review_reason = ""
            connection.execute(
                """
                UPDATE tracking_state
                   SET tracker_status=?,server_presence=?,episode_coverage='NONE',
                       review_status=?,review_reason=?,last_checked=?
                 WHERE tracked_media_id=?
                """,
                (tracker_status, server_presence, review_status, review_reason, timestamp, tracked["id"]),
            )
            if decision_created:
                connection.execute(
                    """
                    INSERT INTO status_history(
                        tracked_media_id,event_type,previous_tracker_status,new_tracker_status,created_at
                    ) VALUES(?,'MANUALLY_MARKED_NOT_ON_SERVER',?,?,?)
                    """,
                    (tracked["id"], previous_status, tracker_status, timestamp),
                )
            return {
                "decision_created": decision_created,
                "remaining_reviews": len(remaining),
                "tracker_status": tracker_status,
                "server_presence": server_presence,
            }

    def save_manual_decision(
        self,
        override_id: str,
        profile_id: str,
        anilist_id: int,
        decision_type: ManualDecisionType,
        reason: str,
        when: datetime,
        *,
        clear_mappings: bool = False,
    ) -> None:
        with self.connect() as connection:
            if clear_mappings:
                self._supersede_active(connection, profile_id, anilist_id, when, decision_type.value)
            connection.execute(
                "UPDATE mapping_overrides SET active=0,cleared_at=? WHERE profile_id=? AND anilist_id=? AND active=1",
                (_iso(when), profile_id, anilist_id),
            )
            connection.execute(
                """
                INSERT INTO mapping_overrides(override_id,profile_id,anilist_id,decision_type,active,reason,created_at)
                VALUES(?,?,?,?,1,?,?)
                """,
                (override_id, profile_id, anilist_id, decision_type.value, reason, _iso(when)),
            )

    def active_manual_decision(self, profile_id: str, anilist_id: int) -> ManualDecisionType | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT decision_type FROM mapping_overrides
                 WHERE profile_id=? AND anilist_id=? AND active=1 ORDER BY created_at DESC LIMIT 1
                """,
                (profile_id, anilist_id),
            ).fetchone()
        return ManualDecisionType(row[0]) if row else None

    def save_coverage_snapshot(
        self,
        mapping_id: str,
        inventory_snapshot_id: str,
        server_presence: str,
        coverage_json: str,
        when: datetime,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO coverage_mapping_snapshots(
                    mapping_id,inventory_snapshot_id,server_presence,coverage_json,created_at
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(mapping_id,inventory_snapshot_id) DO UPDATE SET
                    server_presence=excluded.server_presence,coverage_json=excluded.coverage_json,
                    created_at=excluded.created_at
                """,
                (mapping_id, inventory_snapshot_id, server_presence, coverage_json, _iso(when)),
            )

    @staticmethod
    def _insert_mapping(connection: sqlite3.Connection, mapping: PersistentMapping) -> None:
        target = mapping.target
        connection.execute(
            """
            INSERT INTO media_server_mappings(
                mapping_id,profile_id,anilist_id,target_identity_key,target_type,inventory_item_id,
                root_identifier,relative_path,normalized_path,season_number,library_kind,content_kind,
                inventory_snapshot_id,display_name,path_state,evidence_summary_json,mapping_source,
                confirmation_state,confidence,created_at,updated_at,superseded_at,active,user_note,
                evidence_snapshot_reference
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                mapping.mapping_id, mapping.profile_id, mapping.anilist_id, target.identity_key,
                target.target_type.value, target.inventory_item_id, target.root_identifier,
                target.relative_path, target.normalized_path, target.season_number,
                target.library_kind.value, target.content_kind.value, target.inventory_snapshot_id,
                target.display_name, target.path_state.value, json.dumps(target.evidence_summary),
                mapping.source.value, mapping.confirmation_state.value, mapping.confidence.value,
                _iso(mapping.created_at), _iso(mapping.updated_at), _iso(mapping.superseded_at),
                int(mapping.active), mapping.user_note, mapping.evidence_snapshot_reference,
            ),
        )

    @staticmethod
    def _insert_history(
        connection: sqlite3.Connection,
        mapping: PersistentMapping,
        event_type: str,
        when: datetime | None = None,
    ) -> None:
        state = {
            "target_identity": mapping.target.identity_key,
            "confirmation_state": mapping.confirmation_state.value,
            "active": mapping.active,
            "season_number": mapping.target.season_number,
        }
        connection.execute(
            "INSERT INTO mapping_history(mapping_id,event_type,state_json,occurred_at,source) VALUES(?,?,?,?,?)",
            (mapping.mapping_id, event_type, json.dumps(state, sort_keys=True), _iso(when or mapping.updated_at), mapping.source.value),
        )

    @classmethod
    def _supersede_active(
        cls,
        connection: sqlite3.Connection,
        profile_id: str,
        anilist_id: int,
        when: datetime,
        reason: str,
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM media_server_mappings WHERE profile_id=? AND anilist_id=? AND active=1",
            (profile_id, anilist_id),
        ).fetchall()
        for row in rows:
            mapping = _mapping_from_row(row)
            connection.execute(
                "UPDATE media_server_mappings SET active=0,confirmation_state='SUPERSEDED',superseded_at=?,updated_at=? WHERE mapping_id=?",
                (_iso(when), _iso(when), mapping.mapping_id),
            )
            cls._insert_history(connection, mapping, f"MAPPING_SUPERSEDED:{reason}", when)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _anilist_tracker_status(anilist_status: str, media_format: str, previous_status: str) -> str:
    if media_format == "MOVIE" and previous_status in {"Movie Theatrical Only", "Movie Digitally Available"}:
        return previous_status
    if anilist_status == "RELEASING":
        return "Currently Airing"
    if anilist_status in {"NOT_YET_RELEASED", "HIATUS"}:
        return "Upcoming"
    if anilist_status in {"FINISHED", "CANCELLED"}:
        return "Finished / Ready to Add"
    return previous_status if previous_status not in {"Needs Review", "On Server"} else "Upcoming"


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _evidence_json(evidence: CandidateEvidence) -> str:
    return json.dumps(asdict(evidence), sort_keys=True)


def _target_from_row(row: sqlite3.Row) -> MappingTarget:
    summary = row["evidence_summary_json"] if "evidence_summary_json" in row.keys() else "[]"
    return MappingTarget(
        MappingTargetType(row["target_type"]),
        LibraryKind(row["library_kind"]),
        row["root_identifier"],
        row["relative_path"],
        row["normalized_path"],
        row["inventory_item_id"],
        row["season_number"],
        TrackingContentKind(row["content_kind"]) if row["content_kind"] in {item.value for item in TrackingContentKind} else TrackingContentKind.UNKNOWN,
        row["inventory_snapshot_id"],
        row["display_name"],
        PathState(row["path_state"]),
        tuple(json.loads(summary or "[]")),
    )


def _evidence_from_json(value: str) -> CandidateEvidence:
    data = json.loads(value or "{}")
    data["episode_range"] = tuple(data["episode_range"]) if data.get("episode_range") else None
    data["warnings"] = tuple(data.get("warnings") or ())
    data["score_components"] = tuple(tuple(item) for item in data.get("score_components") or ())
    return CandidateEvidence(**data)


def _candidate_from_row(row: sqlite3.Row) -> MatchCandidate:
    target = _target_from_row(row)
    return MatchCandidate(
        row["candidate_id"], row["session_id"], row["anilist_id"], target,
        _evidence_from_json(row["evidence_json"]), MatchConfidence(row["confidence"]),
        row["score"], bool(row["preselected"]), bool(row["stale"]), row["suggested_next_action"],
    )


def _mapping_from_row(row: sqlite3.Row) -> PersistentMapping:
    return PersistentMapping(
        row["mapping_id"], row["profile_id"], row["anilist_id"], _target_from_row(row),
        MappingSource(row["mapping_source"]), ConfirmationState(row["confirmation_state"]),
        MatchConfidence(row["confidence"]), _datetime(row["created_at"]), _datetime(row["updated_at"]),
        _datetime(row["superseded_at"]), bool(row["active"]), row["user_note"],
        row["evidence_snapshot_reference"],
    )


def _session_from_row(row: sqlite3.Row) -> MatchingSession:
    return MatchingSession(
        row["session_id"], row["profile_id"], row["inventory_snapshot_id"], row["anilist_version"],
        _datetime(row["started_at"]), _datetime(row["completed_at"]), row["candidate_count"],
        row["warning_count"], bool(row["canceled"]), bool(row["partial"]),
    )


def _rejection_from_row(row: sqlite3.Row) -> MatchingRejection:
    details = json.loads(row["target_json"] or "{}")
    return MatchingRejection(
        row["rejection_id"], row["profile_id"], row["anilist_id"],
        MatchingRejectionScope(row["scope"]), row["target_identity"], row["reason"],
        _datetime(row["created_at"]), _datetime(row["expires_at"]), bool(row["active"]),
        _datetime(row["cleared_at"]), MappingSource(row["source"]),
        str(details.get("normalized_path") or ""),
    )


def _review_from_row(row: sqlite3.Row, candidate_ids: tuple[str, ...]) -> MatchingReviewCase:
    return MatchingReviewCase(
        row["review_id"], row["profile_id"], row["anilist_id"], MatchingReviewType(row["review_type"]),
        ReviewCaseState(row["state"]), ReviewSeverity(row["severity"]),
        tuple(json.loads(row["evidence_json"] or "[]")), candidate_ids,
        tuple(json.loads(row["related_mapping_ids_json"] or "[]")), _datetime(row["created_at"]),
        _datetime(row["updated_at"]), row["resolution"], row["user_note"],
    )
