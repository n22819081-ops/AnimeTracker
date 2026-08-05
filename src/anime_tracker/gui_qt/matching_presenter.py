from __future__ import annotations

import json
from collections.abc import Mapping


CONFIDENCE_DESCRIPTIONS = {
    "VERY_STRONG": "150 or more match points with no blocking conflict",
    "STRONG": "110-149 match points with no blocking conflict",
    "POSSIBLE": "75-109 match points with no blocking conflict",
    "WEAK": "45-74 match points with no blocking conflict",
    "INSUFFICIENT_EVIDENCE": "Fewer than 45 match points",
    "CONFLICTING": "Season or media-kind evidence conflicts",
    "REJECTED": "An active rejection applies to this target",
}


def candidate_target(candidate: Mapping[str, object]) -> str:
    name = str(
        candidate.get("display_name")
        or candidate.get("target")
        or candidate.get("relative_path")
        or "Unnamed target"
    )
    season = candidate.get("season_number")
    if season is None:
        return name
    label = f"Season {int(season):02d}"
    return name if label.casefold() in name.casefold() else f"{name} - {label}"


def evidence_data(candidate: Mapping[str, object]) -> dict[str, object]:
    raw = candidate.get("evidence_json") or candidate.get("evidence") or {}
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return {"legacy_summary": raw} if raw.strip() else {}
        return dict(value) if isinstance(value, Mapping) else {"legacy_summary": raw}
    return {}


def evidence_lines(candidate: Mapping[str, object]) -> tuple[str, ...]:
    data = evidence_data(candidate)
    lines: list[str] = []
    matched = str(data.get("matched_title") or "").strip()
    if data.get("exact_title_variant"):
        lines.append(f"Exact title match: {matched}" if matched else "Exact title match")
    elif data.get("title_similarity"):
        lines.append(f"Title similarity: {int(data['title_similarity'])}/100")
    if data.get("season_evidence"):
        season = candidate.get("season_number")
        lines.append(f"Season {int(season):02d} exists" if season is not None else "Explicit season evidence found")
    episode_range = data.get("episode_range")
    if isinstance(episode_range, (list, tuple)) and len(episode_range) == 2:
        lines.append(f"Episodes {episode_range[0]}-{episode_range[1]} detected")
    expected = data.get("expected_episode_count")
    if expected is not None:
        lines.append(f"Expected episode count: {expected}")
    if data.get("movie_evidence"):
        lines.append("Movie-library evidence found")
    if data.get("year_agreement"):
        lines.append("Folder year matches the AniList release year")
    warnings = tuple(str(value).strip() for value in data.get("warnings") or () if str(value).strip())
    if data.get("year_conflict") and not any("folder year" in value.casefold() for value in warnings):
        lines.append("Folder year differs from this AniList entry")
    if data.get("franchise_relation_evidence"):
        lines.append("Existing confirmed parent-folder mapping")
    if data.get("existing_confirmed_mapping"):
        lines.append("Existing confirmed mapping")
    if data.get("rejection_effect"):
        lines.append("Previously rejected target")
    if data.get("absolute_numbering"):
        lines.append("Absolute numbering detected; season scope is unresolved")
    if data.get("mixed_folder_warning"):
        lines.append("Mixed or unrecognized folder evidence")
    for text in warnings:
        if text and text not in lines:
            lines.append(text)
    legacy = str(data.get("legacy_summary") or "").strip()
    if legacy:
        lines.append(legacy)
    if not lines:
        summaries = candidate.get("evidence_summary_json") or ()
        if isinstance(summaries, str):
            try:
                summaries = json.loads(summaries)
            except (TypeError, ValueError):
                summaries = (summaries,)
        lines.extend(str(value) for value in summaries if str(value).strip())
    return tuple(lines) or ("No explanatory evidence was recorded.",)


def evidence_summary(candidate: Mapping[str, object]) -> str:
    return "; ".join(evidence_lines(candidate))


def technical_evidence(candidate: Mapping[str, object]) -> str:
    return json.dumps(evidence_data(candidate), indent=2, sort_keys=True)


def confidence_tooltip(value: object) -> str:
    key = str(value or "").upper()
    return CONFIDENCE_DESCRIPTIONS.get(key, "Confidence is derived from match points and conflict rules.")
