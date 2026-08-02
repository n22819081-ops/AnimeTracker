from __future__ import annotations

import re
import unicodedata

from ...normalization import normalize_title, normalize_title_keep_season, title_tokens
from ..anilist.models import AniListMedia
from ..server_inventory.models import InventoryLibraryItem
from .models import CandidateEvidence, MappingTarget, MatchConfidence


SEASON_PATTERNS = (
    re.compile(r"\bseason\s*0*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\bs0*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})(?:st|nd|rd|th)\s+season\b", re.IGNORECASE),
)


def explicit_season_number(media: AniListMedia) -> int | None:
    for title in media.title.variants:
        for pattern in SEASON_PATTERNS:
            match = pattern.search(title)
            if match:
                return int(match.group(1))
    return None


def normalized_variants(media: AniListMedia) -> tuple[str, ...]:
    values: set[str] = set()
    for title in media.title.variants:
        for value in (normalize_title(title), normalize_title_keep_season(title), _unicode_normalize(title)):
            if value:
                values.add(value)
    return tuple(sorted(values))


def title_match(media: AniListMedia, item: InventoryLibraryItem) -> tuple[int, bool, str]:
    item_base = normalize_title(item.title)
    item_full = normalize_title_keep_season(item.title)
    item_unicode = _unicode_normalize(item.title)
    best_score = 0
    exact = False
    matched = ""
    for original in media.title.variants:
        base = normalize_title(original)
        full = normalize_title_keep_season(original)
        unicode_value = _unicode_normalize(original)
        if item_unicode and unicode_value == item_unicode:
            score = 100
            is_exact = True
        elif item_full and full == item_full:
            score = 100
            is_exact = True
        elif item_base and base == item_base:
            score = 95
            is_exact = True
        else:
            left = title_tokens(original) or set(_unicode_normalize(original).split())
            right = title_tokens(item.title) or set(_unicode_normalize(item.title).split())
            if not left or not right:
                score = 0
            else:
                score = round(100 * len(left & right) / len(left | right))
            is_exact = False
        if score > best_score:
            best_score, exact, matched = score, is_exact, original
    return best_score, exact, matched


def _unicode_normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", text)
    text = "".join(character if character.isalnum() else " " for character in text)
    return " ".join(text.split())


def classify_confidence(score: int, evidence: CandidateEvidence) -> MatchConfidence:
    if evidence.rejection_effect:
        return MatchConfidence.REJECTED
    if evidence.season_conflict or not evidence.media_kind_agreement:
        return MatchConfidence.CONFLICTING
    if score >= 150:
        return MatchConfidence.VERY_STRONG
    if score >= 110:
        return MatchConfidence.STRONG
    if score >= 75:
        return MatchConfidence.POSSIBLE
    if score >= 45:
        return MatchConfidence.WEAK
    return MatchConfidence.INSUFFICIENT_EVIDENCE


def build_evidence(
    media: AniListMedia,
    item: InventoryLibraryItem,
    target: MappingTarget,
    *,
    desired_season: int | None,
    expected_episode_count: int | None,
    related_mapping: bool,
    existing_confirmed: bool,
    rejected: bool,
    mixed_folder: bool,
    absolute_numbering: bool,
    media_kind_agreement: bool,
) -> CandidateEvidence:
    similarity, exact, matched = title_match(media, item)
    components: list[tuple[str, int]] = []
    warnings: list[str] = []
    components.append(("exact title variant" if exact else "title similarity", 70 if exact else round(similarity * 0.5)))

    year_agreement = media.season_year is not None and item.year == media.season_year
    year_conflict = media.season_year is not None and item.year is not None and item.year != media.season_year
    if year_agreement:
        components.append(("year agreement", 15))
    elif year_conflict:
        components.append(("folder year conflict", -12))
        warnings.append("Folder year differs from this AniList entry; explicit season evidence takes precedence.")

    library_agreement = (
        media.media_format.value == "MOVIE" and item.library_kind.value == "MOVIE"
    ) or (
        media.media_format.value != "MOVIE" and item.library_kind.value == "TV"
    )
    if library_agreement:
        components.append(("library kind agreement", 20 if item.library_kind.value == "MOVIE" else 12))
    elif not media_kind_agreement:
        components.append(("media/library conflict", -100))

    season_evidence = desired_season is not None and target.season_number == desired_season
    season_conflict = desired_season is not None and target.season_number != desired_season
    if season_evidence:
        components.append(("explicit season evidence", 50))
    elif season_conflict:
        components.append(("season conflict", -120))

    episode_numbers = _target_episode_numbers(item, target.season_number)
    episode_range = (min(episode_numbers), max(episode_numbers)) if episode_numbers else None
    plausible = bool(
        expected_episode_count
        and episode_numbers
        and max(episode_numbers) <= expected_episode_count
        and len(episode_numbers) <= expected_episode_count
    )
    if plausible:
        components.append(("episode count plausible", 12))
    elif expected_episode_count and episode_numbers and max(episode_numbers) > expected_episode_count:
        warnings.append("Observed episode range exceeds AniList expected episode count.")

    season_zero = target.season_number == 0
    if season_zero:
        components.append(("Season 00 evidence", 28))
        warnings.append("Season 00 is a suggestion only and requires manual scope confirmation.")

    movie_evidence = target.target_type.value == "MOVIE_ITEM" and bool(item.movie_files)
    if movie_evidence:
        components.append(("movie file evidence", 35))
    if related_mapping:
        components.append(("related entry has confirmed parent mapping", 15))
    if existing_confirmed:
        components.append(("existing confirmed mapping", 1000))
    if rejected:
        components.append(("active rejection", -1000))
    if absolute_numbering:
        warnings.append("Absolute episode numbering is unresolved and requires manual episode mapping.")
    if mixed_folder:
        warnings.append("Folder contains mixed or unrecognized media evidence.")

    lowered_titles = " ".join(media.title.variants).casefold()
    if "recap" in lowered_titles or "summary" in lowered_titles:
        warnings.append("AniList identity appears to be a recap; do not substitute the related TV series.")
    if "compilation" in lowered_titles:
        warnings.append("AniList identity appears to be a compilation movie.")

    return CandidateEvidence(
        normalized_title_variants=normalized_variants(media),
        provider_format=media.media_format.value,
        provider_year=media.season_year,
        expected_episode_count=media.episode_count,
        title_similarity=similarity,
        exact_title_variant=exact,
        matched_title=matched,
        year_agreement=year_agreement,
        year_conflict=year_conflict,
        library_kind_agreement=library_agreement,
        media_kind_agreement=media_kind_agreement,
        season_evidence=season_evidence,
        season_conflict=season_conflict,
        episode_count_plausible=plausible,
        episode_range=episode_range,
        season_zero_evidence=season_zero,
        movie_evidence=movie_evidence,
        franchise_relation_evidence=related_mapping,
        existing_confirmed_mapping=existing_confirmed,
        rejection_effect=rejected,
        path_exists=True,
        absolute_numbering=absolute_numbering,
        mixed_folder_warning=mixed_folder,
        warnings=tuple(warnings),
        score_components=tuple(components),
    )


def _target_episode_numbers(item: InventoryLibraryItem, season_number: int | None) -> frozenset[int]:
    if season_number == 0:
        return frozenset(number for group in item.specials for file in group.files for number in file.episode_numbers)
    if season_number is None:
        return frozenset(number for season in item.seasons for file in season.files for number in file.episode_numbers)
    season = next((value for value in item.seasons if value.season_number == season_number), None)
    return season.present_episode_numbers if season else frozenset()
