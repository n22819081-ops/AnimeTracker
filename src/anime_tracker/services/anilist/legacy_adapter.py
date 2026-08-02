from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from ...domain.enums import RelationDirection, RelationType
from .models import AniListMedia, AniListRelation


def _value(row: Mapping[str, Any], key: str, default: Any = "") -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def modern_media_to_legacy_values(media: AniListMedia) -> dict[str, Any]:
    return {
        "anilist_id": media.anilist_id,
        "english_title": media.title.english,
        "romaji_title": media.title.romaji,
        "native_title": media.title.native,
        "alternate_titles": list(media.title.synonyms),
        "format": media.media_format.value,
        "season": media.season,
        "year": media.season_year,
        "total_episodes": media.episode_count,
        "airing_status": media.status.value,
        "start_date": media.start_date.isoformat() if media.start_date else "",
        "expected_end_date": media.end_date.isoformat() if media.end_date else "",
        "cover_image_url": media.cover_images.large or media.cover_images.extra_large or media.cover_images.medium,
        "anilist_url": media.site_url,
        "relation_label": media.relations[0].relation_type.value.replace("_", " ").title() if media.relations else "",
    }


def unresolved_legacy_relation(row: Mapping[str, Any], retrieved_at: datetime | None = None) -> AniListRelation | None:
    label = str(_value(row, "relation_label", "")).strip()
    if not label:
        return None
    normalized = label.upper().replace(" ", "_")
    try:
        relation_type = RelationType(normalized)
    except ValueError:
        relation_type = RelationType.OTHER
    return AniListRelation(
        source_anilist_id=int(_value(row, "anilist_id", 0)),
        target_anilist_id=None,
        relation_type=relation_type,
        target_title="",
        direction=RelationDirection.OUTBOUND,
        retrieved_at=retrieved_at,
        legacy_label=label,
        provider_confirmed=False,
    )


def compare_legacy_values(row: Mapping[str, Any], media: AniListMedia) -> dict[str, tuple[Any, Any]]:
    modern = modern_media_to_legacy_values(media)
    fields = ("english_title", "romaji_title", "native_title", "format", "season", "year", "total_episodes", "airing_status")
    return {field: (_value(row, field, None), modern[field]) for field in fields if _value(row, field, None) != modern[field]}
