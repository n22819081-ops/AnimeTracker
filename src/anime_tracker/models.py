from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AnimeRecord:
    english_title: str
    romaji_title: str
    native_title: str
    alternate_titles: list[str]
    anilist_id: int
    format: str
    season: str
    year: int | None
    total_episodes: int | None
    airing_status: str
    start_date: str
    expected_end_date: str
    cover_image_url: str
    anilist_url: str
    tracker_status: str
    server_status: str = "Not Found"
    detected_server_path: str = ""
    previous_status: str = ""
    notification_state: str = ""
    manual_notes: str = ""
    movie_availability: str = "unknown"
    relation_label: str = ""
    id: int | None = None
    date_added: str = ""
    last_checked: str = ""

    @classmethod
    def from_anilist(cls, payload: dict[str, Any], tracker_status: str) -> "AnimeRecord":
        title = payload.get("title") or {}
        start = payload.get("startDate") or {}
        end = payload.get("endDate") or {}
        cover = payload.get("coverImage") or {}
        synonyms = payload.get("synonyms") or []
        year = payload.get("seasonYear") or start.get("year")
        anilist_id = int(payload["id"])
        return cls(
            english_title=title.get("english") or title.get("romaji") or "",
            romaji_title=title.get("romaji") or title.get("english") or "",
            native_title=title.get("native") or "",
            alternate_titles=[s for s in synonyms if s],
            anilist_id=anilist_id,
            format=payload.get("format") or "",
            season=payload.get("season") or "",
            year=year,
            total_episodes=payload.get("episodes"),
            airing_status=payload.get("status") or "",
            start_date=_date_string(start),
            expected_end_date=_date_string(end),
            cover_image_url=cover.get("large") or cover.get("medium") or "",
            anilist_url=f"https://anilist.co/anime/{anilist_id}",
            tracker_status=tracker_status,
            relation_label=relation_label_from_anilist(payload),
        )


def _date_string(value: dict[str, Any]) -> str:
    year = value.get("year")
    month = value.get("month")
    day = value.get("day")
    if not year:
        return ""
    if month and day:
        return f"{year:04d}-{month:02d}-{day:02d}"
    if month:
        return f"{year:04d}-{month:02d}"
    return str(year)


def relation_label_from_anilist(payload: dict[str, Any]) -> str:
    anime_format = payload.get("format") or ""
    relations = ((payload.get("relations") or {}).get("edges") or [])
    relation_types = [edge.get("relationType") for edge in relations if edge.get("relationType")]
    if "PREQUEL" in relation_types:
        return "Sequel"
    if "SEQUEL" in relation_types:
        return "Prequel"
    if anime_format == "MOVIE":
        return "Movie"
    if anime_format in {"OVA", "ONA", "SPECIAL"}:
        return anime_format
    return ""
