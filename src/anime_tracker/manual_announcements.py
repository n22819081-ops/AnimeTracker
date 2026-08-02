from __future__ import annotations

import json
import re
from dataclasses import dataclass


class ManualAnnouncementValidationError(ValueError):
    pass


class DuplicateManualAnnouncementError(ValueError):
    pass


@dataclass(frozen=True)
class ManualAnnouncement:
    media_type: str
    title: str
    year: int | None = None
    season_number: int | None = None
    episodes: tuple[int, ...] = ()
    id: int | None = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def display_text(self) -> str:
        return format_manual_announcement(self)

    @property
    def normalized_title(self) -> str:
        return normalize_manual_title(self.title)

    @property
    def episodes_json(self) -> str:
        return json.dumps(list(self.episodes), separators=(",", ":"))


def normalize_manual_title(title: str) -> str:
    return " ".join((title or "").strip().split()).casefold()


def parse_episode_expression(value: str) -> tuple[int, ...]:
    text = (value or "").strip()
    if not text:
        raise ManualAnnouncementValidationError("Episodes is required for TV announcements.")
    tokens = text.split(",")
    if any(not token.strip() for token in tokens):
        raise ManualAnnouncementValidationError("Episodes must contain positive numbers or ascending ranges.")
    episodes: set[int] = set()
    for raw_token in tokens:
        token = raw_token.strip()
        single = re.fullmatch(r"\d+", token)
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if single:
            number = int(token)
            if number < 1:
                raise ManualAnnouncementValidationError("Episode numbers must be positive integers.")
            episodes.add(number)
            continue
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start < 1 or end < 1:
                raise ManualAnnouncementValidationError("Episode numbers must be positive integers.")
            if end < start:
                raise ManualAnnouncementValidationError("Episode ranges must be ascending.")
            episodes.update(range(start, end + 1))
            continue
        raise ManualAnnouncementValidationError("Episodes must contain positive numbers or ascending ranges.")
    return tuple(sorted(episodes))


def format_episode_set(episodes: tuple[int, ...] | list[int]) -> str:
    values = sorted(set(int(value) for value in episodes))
    if not values:
        return ""
    ranges: list[tuple[int, int]] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append((start, previous))
        start = previous = value
    ranges.append((start, previous))
    parts = [str(start) if start == end else f"{start}–{end}" for start, end in ranges]
    prefix = "Episode" if len(values) == 1 else "Episodes"
    if len(parts) == 1:
        return f"{prefix} {parts[0]}"
    if len(parts) == 2:
        return f"{prefix} {parts[0]} and {parts[1]}"
    return f"{prefix} " + ", ".join(parts[:-1]) + f", and {parts[-1]}"


def build_manual_announcement(
    media_type: str,
    title: str,
    year: str | int | None = None,
    season: str | int | None = None,
    episodes: str | tuple[int, ...] = "",
    item_id: int | None = None,
) -> ManualAnnouncement:
    normalized_type = "TV_SHOW" if str(media_type).strip().casefold() in {"tv", "tv show", "tv_show"} else "MOVIE" if str(media_type).strip().casefold() == "movie" else ""
    clean_title = " ".join((title or "").strip().split())
    if not normalized_type:
        raise ManualAnnouncementValidationError("Type must be TV Show or Movie.")
    if not clean_title:
        raise ManualAnnouncementValidationError("Title is required.")
    parsed_year = _optional_positive_integer(year, "Year")
    if parsed_year is not None and not 1000 <= parsed_year <= 9999:
        raise ManualAnnouncementValidationError("Year must be a four-digit positive integer.")
    if normalized_type == "MOVIE":
        return ManualAnnouncement("MOVIE", clean_title, parsed_year, id=item_id)
    parsed_season = _required_positive_integer(season, "Season")
    parsed_episodes = episodes if isinstance(episodes, tuple) else parse_episode_expression(episodes)
    if not parsed_episodes or any(int(value) < 1 for value in parsed_episodes):
        raise ManualAnnouncementValidationError("Episodes must contain positive integers.")
    return ManualAnnouncement("TV_SHOW", clean_title, parsed_year, parsed_season, tuple(sorted(set(parsed_episodes))), item_id)


def format_manual_announcement(item: ManualAnnouncement) -> str:
    title = item.title + (f" ({item.year})" if item.year else "")
    if item.media_type == "MOVIE":
        return f"{title} — Movie"
    return f"{title} — Season {item.season_number}, {format_episode_set(item.episodes)}"


def _optional_positive_integer(value: str | int | None, label: str) -> int | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    if not text.isdigit() or int(text) < 1:
        raise ManualAnnouncementValidationError(f"{label} must be a positive integer.")
    return int(text)


def _required_positive_integer(value: str | int | None, label: str) -> int:
    parsed = _optional_positive_integer(value, label)
    if parsed is None:
        raise ManualAnnouncementValidationError(f"{label} is required for TV announcements.")
    return parsed
