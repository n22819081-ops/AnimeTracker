from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterator

from ...domain.enums import AniListStatus, RelationDirection
from ...modernization.schema_v3 import initialize_anilist_test_database
from .models import (
    AniListAiringEpisode,
    AniListMedia,
    AniListRefreshBatch,
    AniListRelation,
    AiringScheduleCacheRecord,
    CacheRecord,
    CacheState,
    CacheStatistics,
    FranchiseGraph,
    FranchiseGroupSuggestion,
    RelationsCacheRecord,
    media_to_payload,
    parse_airing_episode,
    parse_media,
    parse_anilist_status,
    parse_media_kind,
    parse_relation_type,
    RateLimitState,
)

FINISHED_TTL = timedelta(days=30)
RELEASING_TTL = timedelta(hours=1)
UPCOMING_TTL = timedelta(hours=6)
UPCOMING_NEAR_RELEASE_TTL = timedelta(hours=1)
UNKNOWN_TTL = timedelta(hours=6)
RELATIONS_TTL = timedelta(days=7)
AIRING_SCHEDULE_TTL = timedelta(minutes=15)


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def metadata_ttl(media: AniListMedia, now: datetime) -> timedelta:
    if media.status == AniListStatus.FINISHED:
        return FINISHED_TTL
    if media.status == AniListStatus.RELEASING:
        return RELEASING_TTL
    if media.status == AniListStatus.NOT_YET_RELEASED:
        if media.start_date:
            release_at = datetime.combine(media.start_date, time.min, tzinfo=timezone.utc)
            if timedelta(0) <= release_at - now <= timedelta(days=14):
                return UPCOMING_NEAR_RELEASE_TTL
        return UPCOMING_TTL
    return UNKNOWN_TTL


def _datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class AniListCache:
    def __init__(self, database_path: Path, *, test_profile: bool = False, create: bool = False) -> None:
        self.database_path = Path(database_path)
        self.test_profile = test_profile
        if create:
            if not test_profile:
                raise ValueError("Automatic cache schema creation is restricted to test profiles.")
            initialize_anilist_test_database(self.database_path)

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

    def get_media(self, anilist_id: int, now: datetime) -> CacheRecord:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM anilist_media_cache WHERE anilist_id=?", (anilist_id,)).fetchone()
        return self._media_record_from_row(row, now)

    @staticmethod
    def _media_record_from_row(row: sqlite3.Row | None, now: datetime) -> CacheRecord:
        if row is None:
            return CacheRecord(CacheState.MISS)
        expires = _datetime(row["expires_at"])
        state = CacheState.FRESH if expires and expires > now and not bool(row["stale"]) else CacheState.STALE
        try:
            payload = json.loads(row["normalized_payload_json"])
            media = parse_media(payload, _datetime(row["retrieved_at"]) or now)
        except (TypeError, ValueError, json.JSONDecodeError):
            return CacheRecord(
                CacheState.CORRUPT,
                retrieved_at=_datetime(row["retrieved_at"]),
                expires_at=expires,
                last_successful_refresh=_datetime(row["last_successful_refresh"]),
                last_attempted_refresh=_datetime(row["last_attempted_refresh"]),
                last_error="Cached AniList metadata is corrupt.",
                failure_count=int(row["failure_count"]),
            )
        return CacheRecord(
            state,
            media,
            _datetime(row["retrieved_at"]),
            expires,
            _datetime(row["last_successful_refresh"]),
            _datetime(row["last_attempted_refresh"]),
            str(row["last_error_message"] or ""),
            int(row["failure_count"]),
        )

    def get_many_media(self, anilist_ids: tuple[int, ...], now: datetime) -> dict[int, CacheRecord]:
        unique = tuple(dict.fromkeys(anilist_ids))
        rows_by_id: dict[int, sqlite3.Row] = {}
        with self.connect() as connection:
            for offset in range(0, len(unique), 500):
                chunk = unique[offset:offset + 500]
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"SELECT * FROM anilist_media_cache WHERE anilist_id IN ({placeholders})", chunk
                ).fetchall()
                rows_by_id.update({int(row["anilist_id"]): row for row in rows})
        return {media_id: self._media_record_from_row(rows_by_id.get(media_id), now) for media_id in unique}

    def put_media(self, media: AniListMedia, retrieved_at: datetime, *, raw_response: str = "") -> datetime:
        expires_at = retrieved_at + metadata_ttl(media, retrieved_at)
        payload = json.dumps(media_to_payload(media), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO anilist_media_cache(anilist_id,normalized_payload_json,raw_response_json,retrieved_at,expires_at,last_successful_refresh,last_attempted_refresh,last_error_type,last_error_message,failure_count,stale) "
                "VALUES(?,?,?,?,?,?,?,'','',0,0) ON CONFLICT(anilist_id) DO UPDATE SET normalized_payload_json=excluded.normalized_payload_json,raw_response_json=excluded.raw_response_json,retrieved_at=excluded.retrieved_at,expires_at=excluded.expires_at,last_successful_refresh=excluded.last_successful_refresh,last_attempted_refresh=excluded.last_attempted_refresh,last_error_type='',last_error_message='',failure_count=0,stale=0",
                (media.anilist_id, payload, raw_response, retrieved_at.isoformat(), expires_at.isoformat(), retrieved_at.isoformat(), retrieved_at.isoformat()),
            )
            connection.execute("DELETE FROM anilist_title_variants WHERE anilist_id=?", (media.anilist_id,))
            title_rows = [
                ("primary", media.title.primary), ("english", media.title.english),
                ("romaji", media.title.romaji), ("native", media.title.native),
                *(("synonym", item) for item in media.title.synonyms),
            ]
            connection.executemany(
                "INSERT OR IGNORE INTO anilist_title_variants(anilist_id,title_type,title,normalized_title) VALUES(?,?,?,?)",
                [(media.anilist_id, kind, title, normalize_title(title)) for kind, title in title_rows if title],
            )
            connection.execute("DELETE FROM anilist_relations WHERE source_anilist_id=?", (media.anilist_id,))
            self._put_relations(connection, media.relations, retrieved_at)
            connection.execute(
                "INSERT OR REPLACE INTO anilist_relation_state(anilist_id,retrieved_at,expires_at) VALUES(?,?,?)",
                (media.anilist_id, retrieved_at.isoformat(), (retrieved_at + RELATIONS_TTL).isoformat()),
            )
        return expires_at

    @staticmethod
    def _put_relations(connection: sqlite3.Connection, relations: tuple[AniListRelation, ...], retrieved_at: datetime) -> None:
        sources = {item.source_anilist_id for item in relations}
        for source in sources:
            connection.execute("DELETE FROM anilist_relations WHERE source_anilist_id=?", (source,))
        connection.executemany(
            "INSERT OR REPLACE INTO anilist_relations(source_anilist_id,target_anilist_id,relation_type,target_format,target_status,target_title,direction,provider,retrieved_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    item.source_anilist_id, item.target_anilist_id, item.relation_type.value,
                    item.target_format.value, item.target_status.value, item.target_title,
                    item.direction.value, item.provider, (item.retrieved_at or retrieved_at).isoformat(),
                    (retrieved_at + RELATIONS_TTL).isoformat(),
                )
                for item in relations if item.target_anilist_id is not None
            ],
        )

    def record_failure(self, anilist_id: int, attempted_at: datetime, error_type: str, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE anilist_media_cache SET last_attempted_refresh=?,last_error_type=?,last_error_message=?,failure_count=failure_count+1,stale=1 WHERE anilist_id=?",
                (attempted_at.isoformat(), error_type, message, anilist_id),
            )

    def invalidate(self, anilist_id: int, at: datetime) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE anilist_media_cache SET expires_at=?,stale=1 WHERE anilist_id=?",
                ((at - timedelta(microseconds=1)).isoformat(), anilist_id),
            )
            return cursor.rowcount > 0

    def clear_test_profile(self) -> int:
        if not self.test_profile:
            raise PermissionError("Full cache clear is restricted to test profiles.")
        with self.connect() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM anilist_media_cache").fetchone()[0])
            for table in (
                "anilist_title_variants", "anilist_relations", "anilist_relation_state", "anilist_airing_schedule", "anilist_schedule_state",
                "anilist_refresh_items", "anilist_media_cache", "anilist_request_state",
                "franchise_graph_edges", "franchise_graph_nodes", "franchise_group_suggestions",
            ):
                connection.execute(f"DELETE FROM [{table}]")
            return count

    def statistics(self, now: datetime) -> CacheStatistics:
        with self.connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM anilist_media_cache").fetchone()[0])
            fresh = int(connection.execute("SELECT COUNT(*) FROM anilist_media_cache WHERE expires_at>? AND stale=0", (now.isoformat(),)).fetchone()[0])
            failed = int(connection.execute("SELECT COUNT(*) FROM anilist_media_cache WHERE failure_count>0").fetchone()[0])
        return CacheStatistics(total, fresh, total - fresh, failed)

    def save_request_state(self, state: RateLimitState, updated_at: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO anilist_request_state(singleton_id,request_limit,remaining_requests,reset_at,retry_after_seconds,updated_at) VALUES(1,?,?,?,?,?)",
                (
                    state.limit, state.remaining, state.reset_at.isoformat() if state.reset_at else None,
                    state.retry_after_seconds, updated_at.isoformat(),
                ),
            )

    def search_cached_titles(self, text: str, limit: int = 50) -> tuple[AniListMedia, ...]:
        normalized = normalize_title(text)
        with self.connect() as connection:
            ids = [
                int(row[0]) for row in connection.execute(
                    "SELECT DISTINCT anilist_id FROM anilist_title_variants WHERE normalized_title LIKE ? ORDER BY CASE WHEN normalized_title=? THEN 0 ELSE 1 END,title LIMIT ?",
                    (f"%{normalized}%", normalized, limit),
                )
            ]
        values = []
        now = datetime.max.replace(tzinfo=timezone.utc)
        for media_id in ids:
            record = self.get_media(media_id, now)
            if record.media:
                values.append(record.media)
        return tuple(values)

    def put_airing_schedule(self, media_id: int, episodes: tuple[AniListAiringEpisode, ...], retrieved_at: datetime) -> None:
        expires = retrieved_at + AIRING_SCHEDULE_TTL
        with self.connect() as connection:
            connection.execute("DELETE FROM anilist_airing_schedule WHERE anilist_id=?", (media_id,))
            connection.execute(
                "INSERT OR REPLACE INTO anilist_schedule_state(anilist_id,retrieved_at,expires_at) VALUES(?,?,?)",
                (media_id, retrieved_at.isoformat(), expires.isoformat()),
            )
            connection.executemany(
                "INSERT INTO anilist_airing_schedule(schedule_id,anilist_id,episode_number,airing_at,time_until_airing,has_aired,retrieved_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                [
                    (item.schedule_id, media_id, item.episode_number, item.airing_at.isoformat(), item.time_until_airing, int(item.has_aired), retrieved_at.isoformat(), expires.isoformat())
                    for item in episodes
                ],
            )

    def get_airing_schedule_record(self, media_id: int, now: datetime) -> AiringScheduleCacheRecord:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM anilist_airing_schedule WHERE anilist_id=? ORDER BY episode_number", (media_id,)).fetchall()
            state_row = connection.execute("SELECT * FROM anilist_schedule_state WHERE anilist_id=?", (media_id,)).fetchone()
        episodes = tuple(
            AniListAiringEpisode(
                media_id,
                int(row["episode_number"]),
                _datetime(row["airing_at"]),
                int(row["time_until_airing"]) if row["time_until_airing"] is not None else None,
                bool(row["has_aired"]),
                int(row["schedule_id"]) if row["schedule_id"] is not None else None,
            )
            for row in rows if _datetime(row["airing_at"]) is not None
        )
        if state_row is None:
            return AiringScheduleCacheRecord(CacheState.MISS)
        retrieved = _datetime(state_row["retrieved_at"])
        expires = _datetime(state_row["expires_at"])
        state = CacheState.FRESH if expires and expires > now else CacheState.STALE
        return AiringScheduleCacheRecord(state, episodes, retrieved, expires)

    def get_airing_schedule(self, media_id: int) -> tuple[AniListAiringEpisode, ...]:
        return self.get_airing_schedule_record(media_id, datetime.now(timezone.utc)).episodes

    def get_relations(self, media_id: int, now: datetime) -> RelationsCacheRecord:
        with self.connect() as connection:
            rows = tuple(connection.execute("SELECT * FROM anilist_relations WHERE source_anilist_id=? ORDER BY target_anilist_id,relation_type", (media_id,)).fetchall())
            state_row = connection.execute("SELECT * FROM anilist_relation_state WHERE anilist_id=?", (media_id,)).fetchone()
        if state_row is None:
            return RelationsCacheRecord(CacheState.MISS)
        relations = tuple(
            AniListRelation(
                int(row["source_anilist_id"]), int(row["target_anilist_id"]),
                parse_relation_type(row["relation_type"]), parse_media_kind(row["target_format"]),
                parse_anilist_status(row["target_status"]), str(row["target_title"]),
                RelationDirection(str(row["direction"])), str(row["provider"]), _datetime(row["retrieved_at"]),
            )
            for row in rows
        )
        retrieved = _datetime(state_row["retrieved_at"])
        expires = _datetime(state_row["expires_at"])
        state = CacheState.FRESH if expires and expires > now else CacheState.STALE
        return RelationsCacheRecord(state, relations, retrieved, expires)

    def put_franchise_graph(self, graph: FranchiseGraph, media: dict[int, AniListMedia], retrieved_at: datetime) -> None:
        with self.connect() as connection:
            for node in graph.nodes:
                item = media.get(node)
                title = item.title.primary if item else next((edge.target_title for edge in graph.edges if edge.target_anilist_id == node), "")
                media_format = item.media_format.value if item else "UNKNOWN"
                connection.execute(
                    "INSERT OR REPLACE INTO franchise_graph_nodes(anilist_id,title,media_format,tracked,retrieved_at) VALUES(?,?,?,?,?)",
                    (node, title, media_format, int(node in media), retrieved_at.isoformat()),
                )
            connection.executemany(
                "INSERT OR REPLACE INTO franchise_graph_edges(source_anilist_id,target_anilist_id,relation_type,direction,provider,retrieved_at) VALUES(?,?,?,?,?,?)",
                [
                    (edge.source_anilist_id, edge.target_anilist_id, edge.relation_type.value, edge.direction.value, edge.provider, retrieved_at.isoformat())
                    for edge in graph.edges if edge.target_anilist_id is not None
                ],
            )

    def put_franchise_groups(self, groups: tuple[FranchiseGroupSuggestion, ...], updated_at: datetime) -> None:
        with self.connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO franchise_group_suggestions(group_id,member_ids_json,evidence_json,suggested_main_title,confidence,manual_confirmation_state,warnings_json,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                [
                    (
                        group.group_id, json.dumps(group.member_anilist_ids),
                        json.dumps([(edge.source_anilist_id, edge.target_anilist_id, edge.relation_type.value) for edge in group.relation_evidence]),
                        group.suggested_main_title, group.confidence, group.manual_confirmation_state,
                        json.dumps(group.warnings), updated_at.isoformat(),
                    )
                    for group in groups
                ],
            )

    def save_batch(self, batch: AniListRefreshBatch) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO anilist_refresh_batches(started_at,completed_at,requested_count,success_count,failure_count,result,batch_key,total_count,cache_hit_count,network_request_count,rate_limit_pause_count,canceled_count,partial_success,error_summary_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    batch.started_at.isoformat(), batch.completed_at.isoformat(), len(batch.requested_anilist_ids),
                    batch.succeeded, batch.failed, batch.state.value, batch.batch_id, batch.total,
                    batch.cache_hits, batch.network_requests, batch.rate_limit_pauses, batch.canceled_count,
                    int(batch.partial_success), json.dumps(dict(batch.error_summary), sort_keys=True),
                ),
            )
            connection.executemany(
                "INSERT INTO anilist_refresh_items(batch_key,anilist_id,success,cache_hit,network_request_performed,canceled,stale_cache_used,error_type,error_message,started_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        batch.batch_id, item.anilist_id, int(item.success), int(item.cache_hit),
                        int(item.network_request_performed), int(item.canceled), int(item.stale_cache_used),
                        item.error_type, item.error_message,
                        item.started_at.isoformat() if item.started_at else batch.started_at.isoformat(),
                        item.completed_at.isoformat() if item.completed_at else batch.completed_at.isoformat(),
                    )
                    for item in batch.results
                ],
            )
