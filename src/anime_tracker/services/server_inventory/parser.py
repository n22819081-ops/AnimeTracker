from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import FileClassification, SpecialKind


MEDIA_EXTENSIONS = frozenset({
    ".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg",
    ".ts", ".webm", ".wmv",
})
SUBTITLE_EXTENSIONS = frozenset({".ass", ".idx", ".smi", ".srt", ".ssa", ".sub", ".sup", ".vtt"})
ARTWORK_EXTENSIONS = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
METADATA_EXTENSIONS = frozenset({".json", ".nfo", ".xml"})
EXTRA_DIRECTORY_NAMES = frozenset({
    "behind the scenes", "deleted scenes", "extras", "featurettes", "interviews",
    "samples", "shorts", "trailers",
})

SEASON_DIRECTORY = re.compile(r"^(?:season[ ._-]*|s)0*(\d{1,3})$", re.IGNORECASE)
SPECIAL_DIRECTORIES = {
    "special": SpecialKind.SPECIAL,
    "specials": SpecialKind.SPECIAL,
    "season 00": SpecialKind.SPECIAL,
    "season 0": SpecialKind.SPECIAL,
    "s00": SpecialKind.SPECIAL,
    "ova": SpecialKind.OVA,
    "ovas": SpecialKind.OVA,
    "ona": SpecialKind.ONA,
    "onas": SpecialKind.ONA,
}
YEAR_PATTERN = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)")
SXXEXX_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,3})[ ._-]*E(?P<start>\d{1,4})"
    r"(?:(?:[ ._-]*(?:E|-)[ ._-]*)(?P<end>\d{1,4})|E(?P<joined>\d{1,4}))?",
    re.IGNORECASE,
)
X_PATTERN = re.compile(
    r"(?<!\d)(?P<season>\d{1,3})x(?P<start>\d{1,4})"
    r"(?:[ ._-]*(?:x|-)[ ._-]*(?P<end>\d{1,4}))?(?!\d)",
    re.IGNORECASE,
)
LEADING_EPISODE_PATTERN = re.compile(r"^\s*(?P<start>\d{1,4})(?:\s*[-_.]\s*|\s+)")


@dataclass(frozen=True)
class ParsedMediaName:
    classification: FileClassification
    season_number: int | None = None
    episode_numbers: tuple[int, ...] = ()
    special_kind: SpecialKind | None = None


def extract_year(value: str) -> int | None:
    match = YEAR_PATTERN.search(value)
    return int(match.group(1)) if match else None


def season_directory_number(name: str) -> int | None:
    normalized = name.strip().casefold()
    if normalized in SPECIAL_DIRECTORIES:
        return 0
    match = SEASON_DIRECTORY.fullmatch(name.strip())
    return int(match.group(1)) if match else None


def special_directory_kind(name: str) -> SpecialKind | None:
    return SPECIAL_DIRECTORIES.get(name.strip().casefold())


def is_extra_path(parts: tuple[str, ...]) -> bool:
    return any(part.strip().casefold() in EXTRA_DIRECTORY_NAMES for part in parts[:-1])


def classify_non_media(path: Path, relative_parts: tuple[str, ...]) -> FileClassification:
    if is_extra_path(relative_parts):
        return FileClassification.EXTRA
    suffix = path.suffix.casefold()
    if suffix in SUBTITLE_EXTENSIONS:
        return FileClassification.SUBTITLE
    if suffix in ARTWORK_EXTENSIONS:
        return FileClassification.ARTWORK
    if suffix in METADATA_EXTENSIONS:
        return FileClassification.METADATA
    return FileClassification.OTHER


def parse_media_name(
    path: Path,
    *,
    relative_parts: tuple[str, ...],
    library_is_movie: bool,
    folder_season: int | None,
    special_kind: SpecialKind | None,
) -> ParsedMediaName:
    if is_extra_path(relative_parts):
        return ParsedMediaName(FileClassification.EXTRA)
    if path.suffix.casefold() not in MEDIA_EXTENSIONS:
        return ParsedMediaName(classify_non_media(path, relative_parts))
    if library_is_movie:
        return ParsedMediaName(FileClassification.MOVIE)

    stem = path.stem
    for pattern in (SXXEXX_PATTERN, X_PATTERN):
        match = pattern.search(stem)
        if match:
            season = int(match.group("season"))
            start = int(match.group("start"))
            end_value = match.groupdict().get("end") or match.groupdict().get("joined")
            episodes = _episode_range(start, int(end_value) if end_value else start)
            if episodes:
                classification = FileClassification.SPECIAL if season == 0 or special_kind else FileClassification.EPISODE
                return ParsedMediaName(classification, season, episodes, special_kind)

    if folder_season is not None:
        match = LEADING_EPISODE_PATTERN.search(stem)
        if match:
            episode = int(match.group("start"))
            if episode > 0:
                classification = FileClassification.SPECIAL if folder_season == 0 or special_kind else FileClassification.EPISODE
                return ParsedMediaName(classification, folder_season, (episode,), special_kind)

    if special_kind is not None or folder_season == 0:
        return ParsedMediaName(FileClassification.SPECIAL, folder_season or 0, (), special_kind)
    return ParsedMediaName(FileClassification.UNRECOGNIZED_MEDIA, folder_season, (), special_kind)


def _episode_range(start: int, end: int) -> tuple[int, ...]:
    if start <= 0 or end < start or end - start > 99:
        return ()
    return tuple(range(start, end + 1))
