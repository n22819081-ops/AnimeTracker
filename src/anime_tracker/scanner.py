from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .normalization import normalize_title, title_tokens, title_variants
from .path_utils import normalize_windows_path

LOGGER = logging.getLogger(__name__)


@dataclass
class ServerCandidate:
    path: str
    normalized_name: str
    year: int | None
    media_kind: str
    display_name: str = ""
    season_numbers: frozenset[int] = frozenset()


@dataclass
class MatchResult:
    confidence: str
    path: str = ""
    notes: str = ""
    candidates: list["ScoredMatch"] = field(default_factory=list)


@dataclass
class ScoredMatch:
    path: str
    confidence: str
    score: int
    reasons: list[str]
    year: int | None
    media_kind: str


def scan_roots(tv_path: str, movie_path: str) -> list[ServerCandidate]:
    candidates: list[ServerCandidate] = []
    for root, media_kind in ((tv_path, "TV"), (movie_path, "MOVIE")):
        if not root:
            continue
        root_path = Path(root)
        if not root_path.exists():
            LOGGER.info("Jellyfin path does not exist: %s", root)
            continue
        for entry in safe_iterdir(root_path):
            if entry.is_dir():
                season_numbers = detect_season_numbers(entry) if media_kind == "TV" else frozenset()
                candidates.append(
                    ServerCandidate(
                        path=str(entry),
                        normalized_name=normalize_title(entry.name),
                        year=extract_year(entry.name),
                        media_kind=media_kind,
                        display_name=entry.name,
                        season_numbers=season_numbers,
                    )
                )
    return candidates


def safe_iterdir(path: Path):
    try:
        yield from path.iterdir()
    except OSError as exc:
        LOGGER.warning("Could not scan %s: %s", path, exc)


def extract_year(value: str) -> int | None:
    match = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", value)
    return int(match.group(1)) if match else None


SEASON_FOLDER_PATTERN = re.compile(r"^(?:season\s*|s)?0*(\d{1,3})$", re.IGNORECASE)
EPISODE_SEASON_PATTERNS = (
    re.compile(r"\bS(\d{1,3})E\d+\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})x\d+\b", re.IGNORECASE),
)
TRACKED_SEASON_PATTERNS = (
    re.compile(r"\bseason\s*0*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\bs0*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})(?:st|nd|rd|th)\s+season\b", re.IGNORECASE),
)


def detect_season_numbers(show_path: Path) -> frozenset[int]:
    seasons: set[int] = set()
    pending = [show_path]
    visited: set[str] = set()
    while pending:
        directory = pending.pop()
        normalized = normalize_windows_path(str(directory))
        if normalized in visited:
            continue
        visited.add(normalized)
        for child in safe_iterdir(directory):
            if child.is_dir():
                folder_match = SEASON_FOLDER_PATTERN.match(child.name.strip())
                if folder_match:
                    seasons.add(int(folder_match.group(1)))
                if not child.is_symlink():
                    pending.append(child)
            elif child.is_file():
                season = season_number_from_episode_name(child.name)
                if season is not None:
                    seasons.add(season)
    return frozenset(seasons)


def season_number_from_episode_name(name: str) -> int | None:
    for pattern in EPISODE_SEASON_PATTERNS:
        match = pattern.search(name)
        if match:
            return int(match.group(1))
    return None


def tracked_season_number(row) -> int | None:
    values = [
        _row_value(row, "relation_label", ""),
        _row_value(row, "english_title", ""),
        _row_value(row, "romaji_title", ""),
    ]
    try:
        values.extend(json.loads(_row_value(row, "alternate_titles", "[]") or "[]"))
    except (TypeError, json.JSONDecodeError):
        pass
    for value in values:
        for pattern in TRACKED_SEASON_PATTERNS:
            match = pattern.search(str(value or ""))
            if match:
                return int(match.group(1))
    return None


def infer_tracked_seasons(rows) -> dict[int, int | None]:
    rows = list(rows)
    result = {int(row["anilist_id"]): tracked_season_number(row) for row in rows}
    groups: dict[tuple[str, str], list] = {}
    for row in rows:
        if row["format"] == "MOVIE":
            continue
        key = (normalize_title(row["english_title"]), normalize_title(row["romaji_title"]))
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda row: (row["year"] or 9999, row["start_date"] or "", row["anilist_id"]))
        for index, row in enumerate(ordered, start=1):
            result[int(row["anilist_id"])] = result[int(row["anilist_id"])] or index
    return result


def candidate_supports_season(candidate: ServerCandidate, season_number: int | None) -> bool:
    return season_number is None or season_number in candidate.season_numbers


def confirmed_match_has_evidence(confirmed, candidates: list[ServerCandidate], season_number: int | None) -> bool:
    confirmation_type = _row_value(confirmed, "confirmation_type", "manual")
    if confirmation_type == "manual":
        return True
    normalized = normalize_windows_path(confirmed["path"])
    candidate = next((item for item in candidates if normalize_windows_path(item.path) == normalized), None)
    return candidate is not None and candidate_supports_season(candidate, season_number)


def match_record(
    row,
    candidates: list[ServerCandidate],
    rejected_paths: set[str] | None = None,
    season_number: int | None = None,
) -> MatchResult:
    alternates = json.loads(row["alternate_titles"] or "[]")
    variants = title_variants(
        row["english_title"],
        row["romaji_title"],
        row["native_title"],
        alternates=alternates,
    )
    year = row["year"]
    anime_format = row["format"]
    expected_kind = "MOVIE" if anime_format == "MOVIE" else "TV"
    scored: list[ScoredMatch] = []
    rejected = rejected_paths or set()
    expected_season = season_number if season_number is not None else tracked_season_number(row)
    unresolved_active_sequel = (
        expected_kind == "TV"
        and expected_season is None
        and str(_row_value(row, "relation_label", "")).casefold() == "sequel"
        and _row_value(row, "airing_status", "") in {"RELEASING", "NOT_YET_RELEASED"}
    )
    if unresolved_active_sequel:
        return MatchResult("none", notes="An active sequel requires explicit season evidence before server matching.")

    for candidate in candidates:
        if normalize_windows_path(candidate.path) in rejected:
            continue
        if candidate.media_kind != expected_kind:
            continue
        if expected_kind == "TV" and not candidate_supports_season(candidate, expected_season):
            continue
        match = score_candidate(row, variants, candidate, expected_season)
        if match.score >= 45:
            scored.append(match)

    scored.sort(key=lambda item: item.score, reverse=True)
    confident = [item for item in scored if item.confidence == "confident"]
    if len(confident) == 1 and (len(scored) == 1 or confident[0].score - scored[1].score >= 20):
        return MatchResult("confident", confident[0].path, candidates=scored)
    if scored:
        paths = "\n".join(f"{item.score}: {item.path}" for item in scored[:8])
        return MatchResult("uncertain", notes=f"Possible Jellyfin matches require confirmation:\n{paths}", candidates=scored)
    return MatchResult("none", candidates=[])


def score_candidate(row, variants: set[str], candidate: ServerCandidate, season_number: int | None = None) -> ScoredMatch:
    score = 0
    reasons: list[str] = []
    candidate_tokens = title_tokens(candidate.normalized_name)
    if candidate.normalized_name in variants:
        score += 70
        reasons.append("normalized title matched a tracked title or synonym")
    else:
        best_overlap = 0
        best_total = 0
        for variant in variants:
            tokens = title_tokens(variant)
            if not tokens:
                continue
            overlap = len(tokens & candidate_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_total = max(len(tokens), len(candidate_tokens))
        if best_overlap:
            ratio = best_overlap / max(best_total, 1)
            score += int(ratio * 55)
            reasons.append(f"title token overlap {best_overlap}/{best_total}")
    if row["year"] and candidate.year:
        if int(row["year"]) == candidate.year:
            score += 20
            reasons.append("folder year matches AniList year")
        else:
            score -= 25
            reasons.append(f"folder year {candidate.year} differs from AniList year {row['year']}")
    elif row["year"] and not candidate.year:
        reasons.append("folder has no year to compare")
    anime_format = row["format"]
    if anime_format == "MOVIE" and candidate.media_kind == "MOVIE":
        score += 10
        reasons.append("movie format matched movie library")
    elif anime_format != "MOVIE" and candidate.media_kind == "TV":
        score += 10
        reasons.append("series format matched TV library")
    if season_number is not None and season_number in candidate.season_numbers:
        score += 20
        reasons.append(f"Jellyfin season evidence matched Season {season_number}")
    total_episodes = _row_value(row, "total_episodes")
    season = _row_value(row, "season")
    if total_episodes:
        reasons.append(f"AniList episode count: {total_episodes}")
    if season:
        reasons.append(f"AniList season: {season}")
    relation = _row_value(row, "relation_label", "")
    if relation:
        reasons.append(f"AniList relation label: {relation}")
    confidence = "confident" if score >= 90 else "possible"
    return ScoredMatch(candidate.path, confidence, score, reasons, candidate.year, candidate.media_kind)


def _row_value(row, key: str, default=None):
    try:
        if hasattr(row, "keys") and key not in row.keys():
            return default
        return row[key]
    except (KeyError, IndexError):
        return default


def _token_overlap_is_possible(variants: set[str], candidate_name: str) -> bool:
    candidate_tokens = title_tokens(candidate_name)
    if len(candidate_tokens) < 2:
        return False
    for variant in variants:
        tokens = title_tokens(variant)
        if len(tokens) < 2:
            continue
        overlap = tokens & candidate_tokens
        if len(overlap) >= min(3, len(tokens), len(candidate_tokens)):
            return True
    return False


def assert_read_only_scanner() -> None:
    forbidden = {"remove", "unlink", "rename", "replace", "rmdir"}
    used = set(dir(os))
    assert forbidden <= used
