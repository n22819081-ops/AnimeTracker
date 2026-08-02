from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ...domain.enums import LibraryKind
from ...domain.models import ServerEpisode, ServerLibraryItem, ServerMovie, ServerSeason


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class RootScanStatus(StringEnum):
    COMPLETE = "COMPLETE"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    INACCESSIBLE = "INACCESSIBLE"
    CANCELED = "CANCELED"


class DiagnosticCode(StringEnum):
    ROOT_MISSING = "ROOT_MISSING"
    ROOT_INACCESSIBLE = "ROOT_INACCESSIBLE"
    ENTRY_INACCESSIBLE = "ENTRY_INACCESSIBLE"
    STAT_FAILED = "STAT_FAILED"
    SYMLINK_SKIPPED = "SYMLINK_SKIPPED"
    DUPLICATE_PATH_SKIPPED = "DUPLICATE_PATH_SKIPPED"
    UNRECOGNIZED_MEDIA = "UNRECOGNIZED_MEDIA"
    SCAN_CANCELED = "SCAN_CANCELED"


class FileClassification(StringEnum):
    EPISODE = "EPISODE"
    MOVIE = "MOVIE"
    SPECIAL = "SPECIAL"
    UNRECOGNIZED_MEDIA = "UNRECOGNIZED_MEDIA"
    ARTWORK = "ARTWORK"
    SUBTITLE = "SUBTITLE"
    METADATA = "METADATA"
    EXTRA = "EXTRA"
    OTHER = "OTHER"


class SpecialKind(StringEnum):
    SPECIAL = "SPECIAL"
    OVA = "OVA"
    ONA = "ONA"


@dataclass(frozen=True)
class LibraryRoot:
    label: str
    path: str
    library_kind: LibraryKind


@dataclass(frozen=True)
class ScanDiagnostic:
    code: DiagnosticCode
    root_label: str
    relative_path: str = ""
    error_type: str = ""
    message: str = ""


@dataclass(frozen=True)
class InventoryFile:
    path: str
    relative_path: str
    normalized_path: str
    size: int | None
    modified_ns: int | None
    classification: FileClassification
    season_number: int | None = None
    episode_numbers: tuple[int, ...] = ()
    special_kind: SpecialKind | None = None

    @property
    def fingerprint(self) -> tuple[str, int | None, int | None]:
        return self.normalized_path, self.size, self.modified_ns


@dataclass(frozen=True)
class InventorySeason:
    season_number: int
    path: str
    files: tuple[InventoryFile, ...] = ()

    @property
    def present_episode_numbers(self) -> frozenset[int]:
        return frozenset(number for item in self.files for number in item.episode_numbers)


@dataclass(frozen=True)
class InventorySpecialGroup:
    kind: SpecialKind
    path: str
    files: tuple[InventoryFile, ...] = ()


@dataclass(frozen=True)
class InventoryLibraryItem:
    item_id: str
    root_label: str
    library_kind: LibraryKind
    path: str
    normalized_path: str
    title: str
    year: int | None
    seasons: tuple[InventorySeason, ...] = ()
    specials: tuple[InventorySpecialGroup, ...] = ()
    movie_files: tuple[InventoryFile, ...] = ()
    unrecognized_media: tuple[InventoryFile, ...] = ()

    def to_domain_model(self) -> ServerLibraryItem:
        ordinary_seasons = tuple(
            ServerSeason(
                season_number=season.season_number,
                episodes=tuple(
                    ServerEpisode(number, item.path, True, season.season_number == 0)
                    for item in season.files
                    for number in item.episode_numbers
                ),
                path=season.path,
            )
            for season in self.seasons
        )
        special_episodes = tuple(
            ServerEpisode(number, item.path, True, True)
            for group in self.specials
            for item in group.files
            for number in item.episode_numbers
        )
        special_season = (ServerSeason(0, special_episodes, self.specials[0].path),) if self.specials else ()
        seasons = tuple(sorted((*ordinary_seasons, *special_season), key=lambda season: season.season_number))
        movie = ServerMovie(self.movie_files[0].path, True, self.item_id) if self.movie_files else None
        return ServerLibraryItem(
            item_id=self.item_id,
            library_kind=self.library_kind,
            path=self.path,
            title=self.title,
            year=self.year,
            seasons=seasons,
            movie=movie,
            path_exists=True,
        )


@dataclass(frozen=True)
class RootInventory:
    root: LibraryRoot
    status: RootScanStatus
    items: tuple[InventoryLibraryItem, ...] = ()
    diagnostics: tuple[ScanDiagnostic, ...] = ()


@dataclass(frozen=True)
class InventoryStatistics:
    roots_scanned: int = 0
    directories_seen: int = 0
    files_seen: int = 0
    media_files_seen: int = 0
    files_reused: int = 0
    duplicate_paths_skipped: int = 0


@dataclass(frozen=True)
class ServerInventorySnapshot:
    roots: tuple[RootInventory, ...]
    statistics: InventoryStatistics = InventoryStatistics()
    canceled: bool = False

    @property
    def items(self) -> tuple[InventoryLibraryItem, ...]:
        return tuple(item for root in self.roots for item in root.items)

    @property
    def files(self) -> tuple[InventoryFile, ...]:
        files: list[InventoryFile] = []
        for item in self.items:
            files.extend(entry for season in item.seasons for entry in season.files)
            files.extend(entry for group in item.specials for entry in group.files)
            files.extend(item.movie_files)
            files.extend(item.unrecognized_media)
        return tuple(files)
