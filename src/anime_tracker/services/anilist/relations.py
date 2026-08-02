from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from datetime import date
from typing import Iterable, Mapping

from ...domain.enums import RelationType
from .models import AniListMedia, AniListRelation, FranchiseGraph, FranchiseGroupSuggestion

BRANCH_TYPES = {RelationType.MOVIE, RelationType.OVA, RelationType.ONA, RelationType.SPECIAL, RelationType.SIDE_STORY, RelationType.SPIN_OFF}
AMBIGUOUS_TYPES = {RelationType.ALTERNATIVE, RelationType.CHARACTER, RelationType.OTHER}


def build_franchise_graph(relations: Iterable[AniListRelation], extra_nodes: Iterable[int] = ()) -> FranchiseGraph:
    edges = tuple(sorted(
        (item for item in relations if item.target_anilist_id is not None),
        key=lambda item: (item.source_anilist_id, int(item.target_anilist_id or 0), item.relation_type.value, item.direction.value),
    ))
    nodes = set(extra_nodes)
    for edge in edges:
        nodes.add(edge.source_anilist_id)
        nodes.add(int(edge.target_anilist_id))
    warnings = []
    if any(edge.relation_type in AMBIGUOUS_TYPES for edge in edges):
        warnings.append("Alternative, character, or other relations require conservative grouping review.")
    return FranchiseGraph(frozenset(nodes), edges, tuple(warnings))


def connected_component(graph: FranchiseGraph, start_id: int) -> frozenset[int]:
    if start_id not in graph.nodes:
        return frozenset()
    neighbors: dict[int, set[int]] = defaultdict(set)
    for edge in graph.edges:
        target = int(edge.target_anilist_id)
        neighbors[edge.source_anilist_id].add(target)
        neighbors[target].add(edge.source_anilist_id)
    visited = {start_id}
    queue = deque([start_id])
    while queue:
        current = queue.popleft()
        for neighbor in sorted(neighbors[current]):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return frozenset(visited)


def connected_components(graph: FranchiseGraph) -> tuple[frozenset[int], ...]:
    remaining = set(graph.nodes)
    components = []
    while remaining:
        component = connected_component(graph, min(remaining))
        components.append(component)
        remaining -= component
    return tuple(sorted(components, key=lambda item: (min(item), len(item))))


def related_tracked_entries(graph: FranchiseGraph, start_id: int, tracked_ids: Iterable[int]) -> tuple[int, ...]:
    component = connected_component(graph, start_id)
    return tuple(sorted(component.intersection(tracked_ids)))


def likely_main_series_chain(graph: FranchiseGraph, start_id: int) -> tuple[int, ...]:
    allowed = {RelationType.PREQUEL, RelationType.SEQUEL, RelationType.PARENT}
    subgraph = build_franchise_graph((edge for edge in graph.edges if edge.relation_type in allowed), (start_id,))
    return tuple(sorted(connected_component(subgraph, start_id)))


def branch_entries(graph: FranchiseGraph, start_id: int) -> tuple[int, ...]:
    component = connected_component(graph, start_id)
    values = {
        int(edge.target_anilist_id)
        for edge in graph.edges
        if edge.source_anilist_id in component and edge.relation_type in BRANCH_TYPES
    }
    return tuple(sorted(values))


def suggest_franchise_groups(graph: FranchiseGraph, media: Mapping[int, AniListMedia]) -> tuple[FranchiseGroupSuggestion, ...]:
    suggestions = []
    for component in connected_components(graph):
        if len(component) < 2:
            continue
        evidence = tuple(edge for edge in graph.edges if edge.source_anilist_id in component and edge.target_anilist_id in component)
        ambiguous = any(edge.relation_type in AMBIGUOUS_TYPES for edge in evidence)
        main_candidates = sorted(
            (media[item] for item in component if item in media),
            key=lambda item: (item.start_date or item.end_date or date.max, item.anilist_id),
        )
        title = main_candidates[0].title.primary if main_candidates else f"AniList franchise {min(component)}"
        digest = hashlib.sha256(",".join(map(str, sorted(component))).encode("ascii")).hexdigest()[:16]
        warnings = ("Ambiguous relation types require manual confirmation.",) if ambiguous else ()
        suggestions.append(FranchiseGroupSuggestion(
            f"anilist-{digest}", tuple(sorted(component)), evidence, title,
            "MEDIUM" if ambiguous else "HIGH", warnings=warnings,
        ))
    return tuple(suggestions)
