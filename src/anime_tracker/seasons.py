"""Franchise season/movie discovery.

Given one tracked anime, walk its AniList relations to find the rest of the
franchise (further seasons, prequels, movie sequels, spin-offs, and
OVA/ONA/specials), then report which of those entries are already tracked in
the local database.

The walk is a bounded breadth-first search over ``relations.edges``. AniList
only exposes a shallow node (id, format, status, title, season) on each edge,
which is enough to list and to test "already added"; the caller re-fetches the
full media object when it decides to add an entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Relations that point at another season / movie of the same franchise.
SEASON_RELATION_TYPES = {"SEQUEL", "PREQUEL", "MOVIE", "SPIN_OFF", "NEXT_TRIP"}
# Formats that are specials / extra episodes rather than a full season.
SPECIAL_FORMATS = {"OVA", "ONA", "SPECIAL"}
# Relations we do not care about (source material, crossovers, re-runs...).
SKIP_RELATION_TYPES = {
    "ADAPTATION",
    "CHARACTER",
    "SUMMARY",
    "ALTERNATIVE",
    "CREATIVE",
    "COMPILATION",
    "OTHER",
}


@dataclass
class FranchiseEntry:
    anilist_id: int
    title: str
    format: str = ""
    season: int | None = None
    status: str = ""
    relation_type: str = ""
    category: str = ""
    added: bool = False
    row_id: int | None = None

    def display_label(self) -> str:
        title = self.title or f"(AniList {self.anilist_id})"
        if self.season is not None:
            title = f"{title} (Season {self.season})"
        return title


def _classify(relation_type: str, node_format: str) -> str:
    fmt = (node_format or "").upper()
    rt = (relation_type or "").upper()
    if fmt == "MOVIE":
        return "Movie"
    if fmt in SPECIAL_FORMATS:
        return "Special"
    if rt == "PREQUEL":
        return "Prequel Season"
    if rt == "SEQUEL":
        return "Next Season"
    if rt == "SPIN_OFF":
        return "Spin-Off"
    return "Related"


def _want_entry(relation_type: str, node_format: str, include_specials: bool) -> bool:
    fmt = (node_format or "").upper()
    rt = (relation_type or "").upper()
    if rt in SEASON_RELATION_TYPES:
        return True
    if fmt == "MOVIE":
        return True
    if fmt in SPECIAL_FORMATS:
        # Specials are listed only when wanted AND the relation itself is not
        # a skipped kind (a CHARACTER edge to a special is a crossover, not
        # an extra episode of this franchise).
        return include_specials and rt not in SKIP_RELATION_TYPES
    return False


def find_franchise_entries(
    client,
    anilist_id: int,
    *,
    include_specials: bool = True,
    max_depth: int = 4,
) -> list[FranchiseEntry]:
    """Return the rest of the franchise for ``anilist_id`` (excluding itself).

    Follows season/movie relations one level at a time so a multi-season chain
    (S1 -> S2 -> S3) is fully enumerated. Specials/OVA are listed but not
    followed further (they rarely chain).
    """
    root = client.get_by_id(anilist_id)
    seen: set[int] = {int(anilist_id)}
    entries: list[FranchiseEntry] = []
    media_cache: dict[int, dict[str, Any]] = {int(anilist_id): root}

    def fetch(media_id: int) -> dict[str, Any]:
        cached = media_cache.get(media_id)
        if cached is None:
            cached = client.get_by_id(media_id)
            media_cache[media_id] = cached
        return cached

    # queue items: (media_id, depth). Each id is expanded via a full fetch
    # because the shallow relation edge-node does not carry its own relations.
    queue: list[tuple[int, int]] = [(int(anilist_id), 0)]

    while queue:
        media_id, depth = queue.pop(0)
        if depth > max_depth:
            continue
        media = fetch(media_id)
        for edge in (media.get("relations") or {}).get("edges") or []:
            relation_type = (edge.get("relationType") or "").upper()
            node = edge.get("node") or {}
            node_id = node.get("id")
            if not node_id or int(node_id) in seen:
                continue
            seen.add(int(node_id))
            node_format = node.get("format") or ""
            title = node.get("title") or {}
            romaji = title.get("romaji") or title.get("english") or title.get("native") or ""
            if not _want_entry(relation_type, node_format, include_specials):
                continue
            entry = FranchiseEntry(
                anilist_id=int(node_id),
                title=romaji,
                format=node_format or "",
                season=node.get("season"),
                status=node.get("status") or "",
                relation_type=relation_type,
                category=_classify(relation_type, node_format),
            )
            entries.append(entry)
            # Only continue the chain for season/movie relations; specials
            # are leaves so a specials franchise does not explode the walk.
            if relation_type in SEASON_RELATION_TYPES:
                queue.append((int(node_id), depth + 1))

    return entries


def mark_tracked_entries(
    entries: list[FranchiseEntry],
    tracked_anilist_ids: set[int],
    tracked_rows_by_id: dict[int, int] | None = None,
) -> None:
    """Set ``added`` (and ``row_id``) on each entry from the local DB."""
    for entry in entries:
        entry.added = entry.anilist_id in tracked_anilist_ids
        entry.row_id = (tracked_rows_by_id or {}).get(entry.anilist_id)


def tracked_ids_map(db) -> tuple[set[int], dict[int, int]]:
    """Return (set of anilist_ids, {anilist_id: row_id}) for all tracked anime."""
    ids: set[int] = set()
    by_id: dict[int, int] = {}
    for row in db.rows():
        aid = int(row["anilist_id"])
        ids.add(aid)
        by_id.setdefault(aid, int(row["id"]))
    return ids, by_id


__all__ = [
    "FranchiseEntry",
    "SEASON_RELATION_TYPES",
    "SPECIAL_FORMATS",
    "SKIP_RELATION_TYPES",
    "find_franchise_entries",
    "mark_tracked_entries",
    "tracked_ids_map",
]
