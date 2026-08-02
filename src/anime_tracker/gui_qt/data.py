from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class TitleMetadata:
    anilist_id: int
    english: str = ""
    romaji: str = ""
    native: str = ""
    legacy: str = ""


def resolve_display_title(value: TitleMetadata) -> str:
    """Resolve titles identically everywhere without masking missing metadata."""
    return next(
        (title.strip() for title in (value.english, value.romaji, value.native, value.legacy) if title and title.strip()),
        f"AniList {value.anilist_id}",
    )


@dataclass(frozen=True)
class RelationDisplay:
    target_anilist_id: int
    title: str
    relation_type: str
    direction: str
    media_format: str = ""
    status: str = ""


@dataclass(frozen=True)
class AnimeRow:
    anilist_id: int
    title: str
    romaji: str
    native: str
    media_format: str
    season: str
    year: int | None
    anilist_status: str
    tracker_status: str
    server_status: str
    coverage: str
    next_episode: str
    review: str
    last_updated: str
    cover_url: str = ""
    mapping_label: str = "No confirmed server mapping"
    relation_label: str = ""
    archived: bool = False
    english: str = ""
    synonyms: tuple[str, ...] = ()
    episode_count: int | None = None
    next_airing_at: str = ""
    page_url: str = ""
    review_reason: str = ""
    relations: tuple[RelationDisplay, ...] = ()
    expected_episodes: int | None = None
    aired_episodes: int | None = None
    present_episodes: int | None = None
    missing_episodes: tuple[int, ...] = ()

    @property
    def searchable(self) -> str:
        return " ".join(str(value) for value in self.__dict__.values()).casefold()


_TITLE_CTE = """
WITH titles AS (
    SELECT anilist_id,
           MAX(CASE WHEN lower(title_type)='english' THEN title END) english,
           MAX(CASE WHEN lower(title_type)='romaji' THEN title END) romaji,
           MAX(CASE WHEN lower(title_type)='native' THEN title END) native,
           GROUP_CONCAT(CASE WHEN lower(title_type)='synonym' THEN title END, char(31)) synonyms
      FROM media_titles GROUP BY anilist_id
)
"""


class ModernRepository:
    """Read-oriented GUI repository. Widgets never issue SQL."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @property
    def cover_cache_dir(self) -> Path:
        return self.database_path.parent.parent / "cache" / "covers"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def tracked_media(self, *, include_archived: bool = False) -> tuple[AnimeRow, ...]:
        where = "" if include_archived else "WHERE tm.archived_at IS NULL"
        with self.connect() as connection:
            rows = connection.execute(_TITLE_CTE + f"""
                SELECT tm.anilist_id,tm.archived_at,tm.legacy_payload_json,
                       am.media_format,am.season_name,am.season_year,am.episode_count,am.anilist_status,
                       am.cover_image_url,am.page_url,am.source_updated_at,
                       ac.normalized_payload_json,
                       ts.tracker_status,ts.server_presence,ts.episode_coverage,
                       ts.review_status,ts.review_reason,
                       t.english,t.romaji,t.native,t.synonyms,
                       m.target_type,m.season_number,m.display_name,m.relative_path,
                       m.evidence_summary_json
                  FROM tracked_media tm
                  JOIN anilist_media am ON am.anilist_id=tm.anilist_id
                  LEFT JOIN anilist_media_cache ac ON ac.anilist_id=tm.anilist_id
                  LEFT JOIN titles t ON t.anilist_id=tm.anilist_id
                  LEFT JOIN tracking_state ts ON ts.tracked_media_id=tm.id
                  LEFT JOIN media_server_mappings m ON m.mapping_id=(
                       SELECT mapping_id FROM media_server_mappings active_mapping
                        WHERE active_mapping.anilist_id=tm.anilist_id AND active_mapping.active=1
                        ORDER BY active_mapping.updated_at DESC LIMIT 1)
                  {where}
                 ORDER BY COALESCE(t.english,t.romaji,t.native),tm.anilist_id
            """).fetchall()
            relation_rows = connection.execute(_TITLE_CTE + """
                SELECT r.source_anilist_id,r.target_anilist_id,r.relation_type,r.direction,
                       r.target_format,r.target_status,r.target_title,
                       t.english,t.romaji,t.native,
                       tm.legacy_payload_json
                  FROM anilist_relations r
                  LEFT JOIN titles t ON t.anilist_id=r.target_anilist_id
                  LEFT JOIN tracked_media tm ON tm.anilist_id=r.target_anilist_id
                 ORDER BY r.source_anilist_id,r.relation_type,r.target_anilist_id
            """).fetchall()
        relations: dict[int, list[RelationDisplay]] = {}
        for relation in relation_rows:
            legacy = self._legacy_title(relation["legacy_payload_json"])
            title = resolve_display_title(TitleMetadata(
                relation["target_anilist_id"], relation["english"] or "", relation["romaji"] or "",
                relation["native"] or "", legacy or relation["target_title"] or "",
            ))
            relations.setdefault(relation["source_anilist_id"], []).append(RelationDisplay(
                relation["target_anilist_id"], title, relation["relation_type"], relation["direction"],
                relation["target_format"] or "", relation["target_status"] or "",
            ))
        return tuple(self._row(row, tuple(relations.get(row["anilist_id"], ()))) for row in rows)

    def dashboard_counts(self) -> dict[str, int]:
        rows = self.tracked_media()
        return {
            "Currently Airing": sum(row.tracker_status == "Currently Airing" for row in rows),
            "Missing Aired Episodes": sum(row.server_status == "PARTIAL" for row in rows),
            "Finished / Ready to Add": sum("Finished" in row.tracker_status and row.server_status != "COMPLETE" for row in rows),
            "Upcoming This Month": sum(row.tracker_status == "Upcoming" for row in rows),
            "Movies Digitally Available": sum(row.media_format == "MOVIE" and "Digital" in row.tracker_status for row in rows),
            "On Server": sum(row.server_status == "COMPLETE" for row in rows),
            "Needs Review": len(self.review_rows()),
            "Notification Queue Health": self.notification_count("RETRY_WAIT") + self.notification_count("FAILED_PERMANENT"),
        }

    def notification_rows(self) -> tuple[dict, ...]:
        with self.connect() as connection:
            rows = connection.execute(_TITLE_CTE + """
                SELECT o.outbox_id,e.event_type,e.anilist_id,o.channel_purpose,o.created_at,o.status,
                       o.attempt_count,o.next_attempt_at,o.last_error_message,o.delivered_at,o.payload_json,
                       t.english,t.romaji,t.native,tm.legacy_payload_json
                  FROM notification_outbox o JOIN notification_events_v2 e ON e.event_id=o.event_id
                  LEFT JOIN titles t ON t.anilist_id=e.anilist_id
                  LEFT JOIN tracked_media tm ON tm.anilist_id=e.anilist_id
                 ORDER BY o.created_at DESC
            """).fetchall()
        values=[]
        for row in rows:
            value=dict(row); value["display_title"]=resolve_display_title(TitleMetadata(
                row["anilist_id"] or 0,row["english"] or "",row["romaji"] or "",row["native"] or "",self._legacy_title(row["legacy_payload_json"])
            )); values.append(value)
        return tuple(values)

    def notification_count(self, status: str) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT count(*) FROM notification_outbox WHERE status=?", (status,)).fetchone()[0])

    def review_rows(self) -> tuple[dict, ...]:
        with self.connect() as connection:
            rows = connection.execute(_TITLE_CTE + """
                SELECT r.*,t.english,t.romaji,t.native,tm.legacy_payload_json,
                       am.media_format,am.season_name,am.season_year,
                       m.display_name current_mapping,m.target_type mapping_scope,m.season_number mapping_season
                  FROM review_cases r
                  LEFT JOIN titles t ON t.anilist_id=r.anilist_id
                  LEFT JOIN tracked_media tm ON tm.anilist_id=r.anilist_id
                  LEFT JOIN anilist_media am ON am.anilist_id=r.anilist_id
                  LEFT JOIN media_server_mappings m ON m.anilist_id=r.anilist_id AND m.active=1
                 WHERE r.state IN ('OPEN','ACKNOWLEDGED')
                 ORDER BY r.severity DESC,r.created_at
            """).fetchall()
            candidates = connection.execute("""
                SELECT c.review_id,mc.* FROM review_case_candidates c
                  JOIN review_cases r ON r.review_id=c.review_id
                  JOIN server_match_candidates mc ON mc.candidate_id=c.candidate_id
                 WHERE r.state IN ('OPEN','ACKNOWLEDGED') ORDER BY mc.score DESC,c.candidate_id
            """).fetchall()
        by_review: dict[str,list[dict]]={}
        for candidate in candidates:
            by_review.setdefault(candidate["review_id"],[]).append(dict(candidate))
        result=[]
        for row in rows:
            value=dict(row); value["title"]=resolve_display_title(TitleMetadata(
                row["anilist_id"],row["english"] or "",row["romaji"] or "",row["native"] or "",self._legacy_title(row["legacy_payload_json"])
            )); value["candidates"]=tuple(by_review.get(row["review_id"],())); result.append(value)
        return tuple(result)

    def history_rows(self) -> tuple[dict, ...]:
        with self.connect() as connection:
            rows = connection.execute(_TITLE_CTE + """
                SELECT sh.event_type occurred,sh.created_at occurred_at,'Tracker' source,tm.anilist_id,
                       t.english,t.romaji,t.native,tm.legacy_payload_json
                  FROM status_history sh LEFT JOIN tracked_media tm ON tm.id=sh.tracked_media_id
                  LEFT JOIN titles t ON t.anilist_id=tm.anilist_id
                UNION ALL
                SELECT mh.event_type,mh.occurred_at,'Mapping' source,m.anilist_id,
                       t.english,t.romaji,t.native,tm.legacy_payload_json
                  FROM mapping_history mh LEFT JOIN media_server_mappings m ON m.mapping_id=mh.mapping_id
                  LEFT JOIN tracked_media tm ON tm.anilist_id=m.anilist_id LEFT JOIN titles t ON t.anilist_id=m.anilist_id
                ORDER BY occurred_at DESC LIMIT 100
            """).fetchall()
        result=[]
        for row in rows:
            value=dict(row);value["title"]=resolve_display_title(TitleMetadata(row["anilist_id"] or 0,row["english"] or "",row["romaji"] or "",row["native"] or "",self._legacy_title(row["legacy_payload_json"]))) if row["anilist_id"] else "Tracker";result.append(value)
        return tuple(result)

    def recent_events(self,limit:int=10)->tuple[str,...]:
        return tuple(f"{row['title']} · {str(row['occurred']).replace('_',' ').title()}" for row in self.history_rows()[:limit])

    def media_details(self,anilist_id:int)->dict:
        """Load secondary detail evidence only when the user opens a record."""
        with self.connect() as connection:
            history=[dict(row) for row in connection.execute("""SELECT event_type,previous_tracker_status,new_tracker_status,created_at
                FROM status_history sh JOIN tracked_media tm ON tm.id=sh.tracked_media_id WHERE tm.anilist_id=? ORDER BY created_at DESC""",(anilist_id,))]
            mapping_history=[dict(row) for row in connection.execute("""SELECT h.event_type,h.occurred_at,h.source,m.display_name,m.target_type,m.season_number
                FROM mapping_history h JOIN media_server_mappings m ON m.mapping_id=h.mapping_id WHERE m.anilist_id=? ORDER BY h.occurred_at DESC""",(anilist_id,))]
            rejections=[dict(row) for row in connection.execute("SELECT scope,target_identity,reason,created_at,active FROM rejected_match_decisions WHERE anilist_id=? ORDER BY created_at DESC",(anilist_id,))]
            reviews=[dict(row) for row in connection.execute("SELECT review_type,state,severity,evidence_json,created_at,resolution,user_note FROM review_cases WHERE anilist_id=? ORDER BY created_at DESC",(anilist_id,))]
            suppressions=[dict(row) for row in connection.execute("SELECT event_type,channel_purpose,active,reason FROM notification_suppressions WHERE anilist_id=?",(anilist_id,))]
        return {"history":history,"mapping_history":mapping_history,"rejections":rejections,"reviews":reviews,"notification_preferences":suppressions}

    def import_preview(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                "active_titles": connection.execute("SELECT count(*) FROM tracked_media WHERE archived_at IS NULL").fetchone()[0],
                "archived_orphans": connection.execute("SELECT count(*) FROM archived_legacy_records").fetchone()[0],
                "baseline_rows": connection.execute("SELECT count(*) FROM shared_announcement_baselines_v2").fetchone()[0],
                "mappings": connection.execute("SELECT count(*) FROM media_server_mappings").fetchone()[0],
                "rejections": connection.execute("SELECT count(*) FROM rejected_match_decisions").fetchone()[0],
                "candidates": connection.execute("SELECT count(*) FROM server_match_candidates").fetchone()[0],
            }

    @staticmethod
    def _legacy_title(raw: str | None) -> str:
        try:
            payload=json.loads(raw or "{}")
        except (TypeError,ValueError):
            return ""
        return next((str(payload.get(key) or "").strip() for key in ("english_title","romaji_title","native_title","title") if payload.get(key)),"")

    @classmethod
    def _row(cls, row: sqlite3.Row, relations: tuple[RelationDisplay,...]) -> AnimeRow:
        payload=json.loads(row["legacy_payload_json"] or "{}")
        try: cached=json.loads(row["normalized_payload_json"] or "{}")
        except (TypeError,ValueError): cached={}
        cached_title=cached.get("title") or {}; cached_cover=cached.get("coverImage") or {}; next_airing=cached.get("nextAiringEpisode") or {}
        english=row["english"] or cached_title.get("english") or ""
        romaji=row["romaji"] or cached_title.get("romaji") or ""
        native=row["native"] or cached_title.get("native") or ""
        title=resolve_display_title(TitleMetadata(row["anilist_id"],english,romaji,native,cls._legacy_title(row["legacy_payload_json"])))
        synonyms=tuple(value for value in (row["synonyms"] or "").split(chr(31)) if value) or tuple(cached.get("synonyms") or ())
        mapping_label="No confirmed server mapping"
        if row["target_type"]:
            display=row["display_name"] or row["target_type"].replace("_"," ").title()
            mapping_label=f"{display} [{row['target_type']}]"
            if row["season_number"] is not None:mapping_label+=f" · Season {row['season_number']:02d}"
        evidence={}
        try:evidence=json.loads(row["evidence_summary_json"] or "{}")
        except (TypeError,ValueError):pass
        if not isinstance(evidence,dict):evidence={"match_evidence":evidence}
        missing=tuple(int(value) for value in evidence.get("missing_episode_numbers",()) if str(value).isdigit())
        relation_label="\n".join(f"{item.relation_type.replace('_',' ').title()}: {item.title} (AniList {item.target_anilist_id})" for item in relations)
        return AnimeRow(
            row["anilist_id"],title,romaji,native,row["media_format"] or cached.get("format") or "UNKNOWN",
            row["season_name"] or cached.get("season") or "",row["season_year"] or cached.get("seasonYear"),
            row["anilist_status"] or cached.get("status") or "UNKNOWN",row["tracker_status"] or "Unknown",
            row["server_presence"] or "NOT_FOUND",row["episode_coverage"] or "UNKNOWN",
            str(next_airing.get("episode") or payload.get("next_airing_episode") or ""),row["review_status"] or "",
            row["source_updated_at"] or "",row["cover_image_url"] or cached_cover.get("extraLarge") or cached_cover.get("large") or cached_cover.get("medium") or "",
            mapping_label,relation_label,bool(row["archived_at"]),english,synonyms,row["episode_count"] or cached.get("episodes"),
            str(next_airing.get("airingAt") or ""),row["page_url"] or cached.get("siteUrl") or "",row["review_reason"] or "",relations,
            evidence.get("expected_episode_count") or row["episode_count"] or cached.get("episodes"),evidence.get("aired_episode_count"),
            evidence.get("present_episode_count"),missing,
        )
