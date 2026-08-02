from __future__ import annotations

from datetime import datetime, timezone

from anime_tracker.domain.enums import AniListStatus, LibraryKind, MediaKind
from anime_tracker.services.anilist.models import AniListMedia, AniListRelation, AniListTitle
from anime_tracker.services.server_inventory.models import (
    FileClassification,
    InventoryFile,
    InventoryLibraryItem,
    InventorySeason,
    InventorySpecialGroup,
    InventoryStatistics,
    LibraryRoot,
    RootInventory,
    RootScanStatus,
    ServerInventorySnapshot,
    SpecialKind,
)


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def media(
    title="Example Anime",
    *,
    anilist_id=100,
    english=None,
    romaji="",
    native="",
    synonyms=(),
    kind=MediaKind.TV,
    status=AniListStatus.FINISHED,
    year=2024,
    episodes=12,
    updated=1,
    relations=(),
):
    english = title if english is None else english
    return AniListMedia(
        anilist_id,
        None,
        AniListTitle(title, english, romaji, native, tuple(synonyms)),
        kind,
        status,
        season_year=year,
        episode_count=episodes,
        provider_updated_at=updated,
        relations=tuple(relations),
    )


def relation(source=100, target=50, relation_type=None):
    from anime_tracker.domain.enums import RelationType

    return AniListRelation(source, target, relation_type or RelationType.PREQUEL)


def episode_file(item_id, season, episode, *, absolute=False, name=""):
    name = name or f"Example.S{season:02d}E{episode:02d}.mkv"
    path = rf"X:\Synthetic\{item_id}\Season {season:02d}\{name}"
    return InventoryFile(
        path,
        name,
        path.casefold(),
        1,
        1,
        FileClassification.UNRECOGNIZED_MEDIA if absolute else FileClassification.EPISODE,
        None if absolute else season,
        () if absolute else (episode,),
        None,
        (episode,) if absolute else (),
    )


def inventory_item(
    title="Example Anime (2024)",
    *,
    item_id="item-example",
    year=2024,
    seasons=None,
    specials=(),
    movie=False,
    kind=LibraryKind.TV,
    unrecognized=(),
    root="TV",
):
    seasons = {1: range(1, 13)} if seasons is None and not movie else seasons or {}
    path = rf"X:\Synthetic\{root}\{title}"
    season_models = tuple(
        InventorySeason(
            number,
            rf"{path}\Season {number:02d}",
            tuple(episode_file(item_id, number, episode) for episode in episodes),
        )
        for number, episodes in sorted(seasons.items())
    )
    special_models = tuple(
        InventorySpecialGroup(
            special_kind,
            rf"{path}\{special_kind.value}",
            tuple(
                InventoryFile(
                    rf"{path}\{special_kind.value}\Special.S00E{episode:02d}.mkv",
                    f"Special.S00E{episode:02d}.mkv",
                    rf"{path}\{special_kind.value}\Special.S00E{episode:02d}.mkv".casefold(),
                    1,
                    1,
                    FileClassification.SPECIAL,
                    0,
                    (episode,),
                    special_kind,
                )
                for episode in episodes
            ),
        )
        for special_kind, episodes in specials
    )
    movie_files = ()
    if movie:
        movie_path = rf"{path}\{title}.mkv"
        movie_files = (InventoryFile(
            movie_path, f"{title}.mkv", movie_path.casefold(), 1, 1, FileClassification.MOVIE,
        ),)
    return InventoryLibraryItem(
        item_id,
        root,
        kind,
        path,
        path.casefold(),
        title,
        year,
        season_models,
        special_models,
        movie_files,
        tuple(unrecognized),
    )


def snapshot(*items, reverse=False, partial=False):
    items = tuple(reversed(items)) if reverse else tuple(items)
    tv = tuple(item for item in items if item.library_kind == LibraryKind.TV)
    movies = tuple(item for item in items if item.library_kind == LibraryKind.MOVIE)
    roots = []
    if tv:
        roots.append(RootInventory(
            LibraryRoot("TV", r"X:\Synthetic\TV", LibraryKind.TV),
            RootScanStatus.PARTIAL if partial else RootScanStatus.COMPLETE,
            tv,
        ))
    if movies:
        roots.append(RootInventory(
            LibraryRoot("Movies", r"X:\Synthetic\Movies", LibraryKind.MOVIE),
            RootScanStatus.COMPLETE,
            movies,
        ))
    if not roots:
        roots.append(RootInventory(
            LibraryRoot("TV", r"X:\Synthetic\TV", LibraryKind.TV), RootScanStatus.EMPTY,
        ))
    return ServerInventorySnapshot(tuple(roots), InventoryStatistics())
