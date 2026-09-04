from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .normalization import NOISE_WORDS, normalize_title, title_tokens, title_variants
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
    re.compile(r"\bpart\s+(i{1,3}|iv|v?i{1,3}|\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(second|third)\s+season\b", re.IGNORECASE),
)
# Trailing bare digit / "Ni" only counts as a season for sequel/prequel rows,
# so titles like "86" or "22/7" are never misread as season numbers.
TRAILING_SEASON_PATTERN = re.compile(r"\b(\d{1,3})\s*[!！?？]*\s*$")
TRAILING_NII_PATTERN = re.compile(r"\bni\s*[!！?？]*\s*$", re.IGNORECASE)
_ROMAN_SEASON_VALUES = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "vi": 6, "vii": 7, "viii": 8}
_SEQUEL_RELATION_LABELS = {"sequel", "prequel"}


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


def _season_value_from_match(match) -> int | None:
    if not match:
        return None
    token = str(match.group(1) or "").strip()
    if token.isdigit():
        return int(token)
    roman = token.casefold()
    if roman in _ROMAN_SEASON_VALUES:
        return _ROMAN_SEASON_VALUES[roman]
    spelled = token.casefold()
    for name, number in (("first", 1), ("second", 2), ("third", 3), ("fourth", 4)):
        if spelled == name:
            return number
    return None


def _strip_season_indicators(title: str, strip_trailing: bool = True) -> str:
    text = unicodedata.normalize("NFKD", str(title or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"\bseason\s*0*\d{1,3}\b", " ", text)
    text = re.sub(r"\bs\d{1,3}\b", " ", text)
    text = re.sub(r"\b\d{1,3}(?:st|nd|rd|th)\s+season\b", " ", text)
    text = re.sub(r"\bpart\s+(?:i{1,3}|iv|v?i{1,3}|\d{1,3})\b", " ", text)
    text = re.sub(r"\bsecond\s+season\b", " ", text)
    text = re.sub(r"\bthird\s+season\b", " ", text)
    if strip_trailing:
        text = re.sub(r"\bni\s*[!！?？]*\s*$", " ", text)
        text = re.sub(r"\b\d{1,3}\s*[!！?？]*\s*$", " ", text)
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = " ".join(part for part in text.split() if part not in NOISE_WORDS)
    return text.strip()


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
            number = _season_value_from_match(match)
            if number is not None:
                return number
    # A bare trailing digit ("Iruma-kun 2") or "Ni" only counts as a season
    # indicator when AniList already marks the row as a sequel/prequel.
    if str(_row_value(row, "relation_label", "")).casefold() in _SEQUEL_RELATION_LABELS:
        for value in values:
            text = str(value or "").strip()
            trailing_nii = TRAILING_NII_PATTERN.search(text)
            if trailing_nii:
                return 2
            trailing = TRAILING_SEASON_PATTERN.search(text)
            if trailing:
                return int(trailing.group(1))
    return None


def _franchise_stem(row) -> str:
    # Season indicators are stripped from every row in the franchise so the
    # base entry and its sequels share one stem ("Iruma-kun" / "Iruma-kun 2"
    # both -> "mairimashita! iruma-kun"). Titles without indicators are
    # unaffected, so single-season shows never merge into a franchise group.
    english = _strip_season_indicators(_row_value(row, "english_title", ""))
    romaji = _strip_season_indicators(_row_value(row, "romaji_title", ""))
    stem = " ".join(part for part in (english, romaji) if part)
    if not stem:
        native = _strip_season_indicators(_row_value(row, "native_title", ""))
        stem = native
    return stem


def _group_rows(rows: list) -> dict[str, list]:
    groups: dict[str, list] = {}
    for row in rows:
        key = (
            normalize_title(_row_value(row, "english_title", "")),
            normalize_title(_row_value(row, "romaji_title", "")),
        )
        groups.setdefault(f"base:{key[0]}|{key[1]}", []).append(row)
    stem_groups: dict[str, list] = {}
    for row in rows:
        stem = _franchise_stem(row)
        if stem:
            stem_groups.setdefault(stem, []).append(row)
    for stem, group in stem_groups.items():
        if len(group) >= 2:
            for row in group:
                groups.pop(
                    f"base:{normalize_title(_row_value(row, 'english_title', ''))}|{normalize_title(_row_value(row, 'romaji_title', ''))}",
                    None,
                )
            groups[f"stem:{stem}"] = group
    return groups


def infer_tracked_seasons(rows) -> dict[int, int | None]:
    rows = list(rows)
    result = {int(row["anilist_id"]): tracked_season_number(row) for row in rows}
    # Group by franchise stem so the base entry and its sequels share one group.
    for group in _group_rows(rows).values():
        if len(group) < 2:
            continue
        ordered = sorted(
            group,
            key=lambda row: (
                _row_value(row, "year", None) or 9999,
                _row_value(row, "start_date", "") or "",
                int(row["anilist_id"]),
            ),
        )
        unmarked = [row for row in ordered if result[int(row["anilist_id"])] is None]
        if not unmarked:
            continue
        explicit = [
            result[int(row["anilist_id"])]
            for row in ordered
            if result[int(row["anilist_id"])] is not None
        ]
        if explicit and 1 not in explicit:
            # The franchise has explicit season indicators but no Season 1 row:
            # the earliest unmarked row is the missing Season 1.
            result[int(unmarked[0]["anilist_id"])] = 1
        else:
            # Either no explicit indicators at all, or Season 1 is already
            # explicit: infer by group order for every unmarked row (the
            # original behavior, preserved verbatim).
            for idx, row in enumerate(ordered, start=1):
                if result[int(row["anilist_id"])] is None:
                    result[int(row["anilist_id"])] = idx
    return result


def multi_season_ids(rows) -> set[int]:
    """anilist_ids of franchise entries that carry no reliable season number.

    Only *ambiguous* entries qualify: sequel/prequel rows whose titles have no
    season indicator (e.g. "Multi Show" with relation=Sequel). The earliest row
    in a franchise group is the base entry and resolves to Season 1, so it is
    never ambiguous — this keeps "Season 01 matches Season 1" working while
    stopping a None-season sequel from auto-matching any franchise folder.
    """
    ids: set[int] = set()
    for group in _group_rows(rows).values():
        if len(group) < 2:
            continue
        ordered = sorted(
            group,
            key=lambda row: (
                _row_value(row, "year", None) or 9999,
                _row_value(row, "start_date", "") or "",
                int(row["anilist_id"]),
            ),
        )
        for row in ordered[1:]:
            if (
                str(_row_value(row, "format", "")).casefold() != "movie"
                and str(_row_value(row, "relation_label", "")).casefold() in _SEQUEL_RELATION_LABELS
                and tracked_season_number(row) is None
            ):
                ids.add(int(row["anilist_id"]))
    return ids


def candidate_supports_season(
    candidate: ServerCandidate,
    season_number: int | None,
    multi_season: bool = False,
) -> bool:
    if season_number is not None:
        return season_number in candidate.season_numbers
    # Unknown season: only safe to accept a flat (season-less) folder for
    # multi-season franchises; a single-season show keeps the old behavior.
    return not candidate.season_numbers or not multi_season


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
    multi_season_ids: set[int] | None = None,
) -> MatchResult:
    anilist_id = _row_value(row, "anilist_id", -1)
    multi_season = anilist_id in (multi_season_ids or set())
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
    if expected_kind == "TV" and expected_season is None and multi_season:
        return MatchResult(
            "uncertain",
            notes="Season number could not be determined for this franchise entry; "
            "please review which Jellyfin season folder matches it.",
            candidates=[],
        )

    for candidate in candidates:
        if normalize_windows_path(candidate.path) in rejected:
            continue
        if candidate.media_kind != expected_kind:
            continue
        if expected_kind == "TV" and not candidate_supports_season(candidate, expected_season, multi_season):
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
    # A candidate only earns the season-evidence corroboration bonus if its
    # title already positively matches the tracked show (exact match, or a
    # substantial share of tokens -- >=2 shared AND >=40% of the title). A
    # folder sharing only a couple of generic words (e.g. "in", "a") is noise
    # and must not let folder metadata -- a "Season 01" subfolder plus a
    # matching year -- lift an unrelated folder past the "possible" threshold.
    # That was turning genuinely missing shows into spurious Needs-Review. This
    # only gates the corroboration bonus; the core rule that a None season
    # never means "any season" is left untouched.
    title_positive = False
    if candidate.normalized_name in variants:
        score += 70
        reasons.append("normalized title matched a tracked title or synonym")
        title_positive = True
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
        best_ratio = best_overlap / max(best_total, 1) if best_overlap else 0.0
        if best_overlap:
            score += int(best_ratio * 55)
            reasons.append(f"title token overlap {best_overlap}/{best_total}")
        if best_overlap >= 2 and best_ratio >= 0.4:
            title_positive = True
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
    if season_number is not None and season_number in candidate.season_numbers and title_positive:
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
