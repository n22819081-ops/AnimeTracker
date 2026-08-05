from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ...domain.enums import LibraryKind
from ...path_utils import normalize_windows_path
from ..anilist.cancellation import Cancellation
from .models import (
    DiagnosticCode,
    FileClassification,
    InventoryFile,
    InventoryLibraryItem,
    InventorySeason,
    InventorySpecialGroup,
    InventoryStatistics,
    LibraryRoot,
    RootInventory,
    RootScanStatus,
    ScanDiagnostic,
    ServerInventorySnapshot,
    SpecialKind,
)
from .parser import (
    extract_year,
    parse_media_name,
    season_directory_number,
    special_directory_kind,
)


@dataclass
class _Counters:
    roots_scanned: int = 0
    directories_seen: int = 0
    files_seen: int = 0
    media_files_seen: int = 0
    files_reused: int = 0
    duplicate_paths_skipped: int = 0

    def freeze(self) -> InventoryStatistics:
        return InventoryStatistics(**vars(self))


@dataclass
class _ItemBuilder:
    item_path: Path
    item_title: str
    seasons: dict[int, list[InventoryFile]]
    season_paths: dict[int, str]
    specials: dict[SpecialKind, list[InventoryFile]]
    special_paths: dict[SpecialKind, str]
    movie_files: list[InventoryFile]
    unrecognized: list[InventoryFile]

    @classmethod
    def create(cls, path: Path, title: str) -> _ItemBuilder:
        return cls(path, title, {}, {}, {}, {}, [], [])


class FilesystemInventoryService:
    """Read-only, deterministic filesystem inventory with no matching behavior."""

    def __init__(
        self,
        *,
        scandir: Callable[[str], object] = os.scandir,
        stat: Callable[[str], os.stat_result] = os.stat,
    ) -> None:
        self._scandir = scandir
        self._stat = stat

    def scan(
        self,
        roots: tuple[LibraryRoot, ...] | list[LibraryRoot],
        *,
        previous_snapshot: ServerInventorySnapshot | None = None,
        token: Cancellation | None = None,
    ) -> ServerInventorySnapshot:
        counters = _Counters()
        seen_paths: set[str] = set()
        previous_files = {
            item.normalized_path: item
            for item in (previous_snapshot.files if previous_snapshot else ())
        }
        inventories: list[RootInventory] = []
        canceled = False
        ordered_roots = sorted(roots, key=lambda root: (root.label.casefold(), normalize_windows_path(root.path)))
        for root in ordered_roots:
            if self._is_canceled(token):
                canceled = True
                inventories.append(self._canceled_root(root))
                continue
            inventory = self._scan_root(root, previous_files, seen_paths, counters, token)
            inventories.append(inventory)
            canceled = canceled or inventory.status == RootScanStatus.CANCELED
        return ServerInventorySnapshot(tuple(inventories), counters.freeze(), canceled)

    def _scan_root(
        self,
        root: LibraryRoot,
        previous_files: dict[str, InventoryFile],
        seen_paths: set[str],
        counters: _Counters,
        token: Cancellation | None,
    ) -> RootInventory:
        root_path = Path(root.path)
        diagnostics: list[ScanDiagnostic] = []
        try:
            root_stat = self._stat(str(root_path))
            if not _is_directory_mode(root_stat.st_mode):
                raise NotADirectoryError(str(root_path))
        except FileNotFoundError:
            return RootInventory(root, RootScanStatus.MISSING, diagnostics=(ScanDiagnostic(
                DiagnosticCode.ROOT_MISSING, root.label, message="The configured root does not exist.",
            ),))
        except (PermissionError, OSError) as exc:
            return RootInventory(root, RootScanStatus.INACCESSIBLE, diagnostics=(ScanDiagnostic(
                DiagnosticCode.ROOT_INACCESSIBLE,
                root.label,
                error_type=type(exc).__name__,
                message="The configured root could not be read.",
            ),))

        entries, root_failed = self._entries(root_path, root, "", diagnostics)
        if root_failed:
            return RootInventory(root, RootScanStatus.INACCESSIBLE, diagnostics=tuple(diagnostics))

        counters.roots_scanned += 1
        counters.directories_seen += 1
        items: list[InventoryLibraryItem] = []
        partial = False
        for entry in entries:
            if self._is_canceled(token):
                diagnostics.append(ScanDiagnostic(
                    DiagnosticCode.SCAN_CANCELED, root.label, message="The inventory scan was canceled.",
                ))
                return RootInventory(root, RootScanStatus.CANCELED, tuple(_sort_items(items)), tuple(_sort_diagnostics(diagnostics)))
            path = Path(entry.path)
            relative = path.name
            try:
                if _is_link_or_junction(entry, path):
                    diagnostics.append(ScanDiagnostic(
                        DiagnosticCode.SYMLINK_SKIPPED, root.label, relative,
                        message="A symbolic link or junction was skipped to avoid recursion hazards.",
                    ))
                    continue
                if entry.is_dir(follow_symlinks=False):
                    normalized = normalize_windows_path(str(path))
                    if not self._claim_path(normalized, root, relative, diagnostics, seen_paths, counters):
                        continue
                    item, item_partial, item_canceled = self._scan_item(
                        root, path, previous_files, seen_paths, counters, diagnostics, token,
                    )
                    if item is not None:
                        items.append(item)
                    partial = partial or item_partial
                    if item_canceled:
                        diagnostics.append(ScanDiagnostic(
                            DiagnosticCode.SCAN_CANCELED, root.label, relative,
                            message="The inventory scan was canceled.",
                        ))
                        return RootInventory(root, RootScanStatus.CANCELED, tuple(_sort_items(items)), tuple(_sort_diagnostics(diagnostics)))
                elif entry.is_file(follow_symlinks=False):
                    direct_item, file_partial = self._scan_direct_file(
                        root, path, previous_files, seen_paths, counters, diagnostics,
                    )
                    if direct_item is not None:
                        items.append(direct_item)
                    partial = partial or file_partial
            except OSError as exc:
                partial = True
                diagnostics.append(self._entry_diagnostic(root, relative, exc))

        status = RootScanStatus.PARTIAL if partial else RootScanStatus.COMPLETE if items else RootScanStatus.EMPTY
        return RootInventory(root, status, tuple(_sort_items(items)), tuple(_sort_diagnostics(diagnostics)))

    def _scan_item(
        self,
        root: LibraryRoot,
        item_path: Path,
        previous_files: dict[str, InventoryFile],
        seen_paths: set[str],
        counters: _Counters,
        diagnostics: list[ScanDiagnostic],
        token: Cancellation | None,
    ) -> tuple[InventoryLibraryItem | None, bool, bool]:
        builder = _ItemBuilder.create(item_path, item_path.name)
        partial, canceled = self._walk_item(
            root,
            item_path,
            item_path,
            builder,
            previous_files,
            seen_paths,
            counters,
            diagnostics,
            token,
            folder_season=None,
            special_kind=None,
        )
        item = self._freeze_item(root, builder)
        return item, partial, canceled

    def _walk_item(
        self,
        root: LibraryRoot,
        item_path: Path,
        directory: Path,
        builder: _ItemBuilder,
        previous_files: dict[str, InventoryFile],
        seen_paths: set[str],
        counters: _Counters,
        diagnostics: list[ScanDiagnostic],
        token: Cancellation | None,
        *,
        folder_season: int | None,
        special_kind: SpecialKind | None,
    ) -> tuple[bool, bool]:
        if self._is_canceled(token):
            return False, True
        relative_directory = _relative_path(directory, item_path)
        entries, failed = self._entries(directory, root, relative_directory, diagnostics)
        if failed:
            return True, False
        if directory != item_path:
            counters.directories_seen += 1
        partial = False
        for entry in entries:
            if self._is_canceled(token):
                return partial, True
            child = Path(entry.path)
            relative = _relative_path(child, item_path)
            try:
                if _is_link_or_junction(entry, child):
                    diagnostics.append(ScanDiagnostic(
                        DiagnosticCode.SYMLINK_SKIPPED, root.label, relative,
                        message="A symbolic link or junction was skipped to avoid recursion hazards.",
                    ))
                    continue
                normalized = normalize_windows_path(str(child))
                if not self._claim_path(normalized, root, relative, diagnostics, seen_paths, counters):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    explicit_special = special_directory_kind(child.name)
                    child_special = explicit_special or special_kind
                    parsed_season = season_directory_number(child.name)
                    child_season = parsed_season if parsed_season is not None else folder_season
                    if explicit_special is not None:
                        builder.specials.setdefault(explicit_special, [])
                        builder.special_paths.setdefault(explicit_special, str(child))
                    elif parsed_season is not None and child_special is None:
                        builder.seasons.setdefault(parsed_season, [])
                        builder.season_paths.setdefault(parsed_season, str(child))
                    nested_partial, canceled = self._walk_item(
                        root, item_path, child, builder, previous_files, seen_paths, counters,
                        diagnostics, token, folder_season=child_season, special_kind=child_special,
                    )
                    partial = partial or nested_partial
                    if canceled:
                        return partial, True
                elif entry.is_file(follow_symlinks=False):
                    observed, stat_failed = self._observe_file(
                        root,
                        item_path,
                        child,
                        previous_files,
                        counters,
                        diagnostics,
                        folder_season=folder_season,
                        special_kind=special_kind,
                    )
                    partial = partial or stat_failed
                    if observed is not None:
                        self._add_file(builder, observed, directory)
            except OSError as exc:
                partial = True
                diagnostics.append(self._entry_diagnostic(root, relative, exc))
        return partial, False

    def _scan_direct_file(
        self,
        root: LibraryRoot,
        path: Path,
        previous_files: dict[str, InventoryFile],
        seen_paths: set[str],
        counters: _Counters,
        diagnostics: list[ScanDiagnostic],
    ) -> tuple[InventoryLibraryItem | None, bool]:
        normalized = normalize_windows_path(str(path))
        if not self._claim_path(normalized, root, path.name, diagnostics, seen_paths, counters):
            return None, False
        builder = _ItemBuilder.create(path, path.stem)
        observed, partial = self._observe_file(
            root, path.parent, path, previous_files, counters, diagnostics,
            folder_season=None, special_kind=None,
        )
        if observed is None:
            return None, partial
        self._add_file(builder, observed, path.parent)
        return self._freeze_item(root, builder), partial

    def _observe_file(
        self,
        root: LibraryRoot,
        item_path: Path,
        path: Path,
        previous_files: dict[str, InventoryFile],
        counters: _Counters,
        diagnostics: list[ScanDiagnostic],
        *,
        folder_season: int | None,
        special_kind: SpecialKind | None,
    ) -> tuple[InventoryFile | None, bool]:
        counters.files_seen += 1
        relative = _relative_path(path, item_path)
        normalized = normalize_windows_path(str(path))
        size: int | None = None
        modified_ns: int | None = None
        stat_failed = False
        try:
            details = self._stat(str(path))
            size = details.st_size
            modified_ns = details.st_mtime_ns
        except OSError as exc:
            stat_failed = True
            diagnostics.append(ScanDiagnostic(
                DiagnosticCode.STAT_FAILED,
                root.label,
                relative,
                type(exc).__name__,
                "File metadata could not be read; the filename was still inventoried.",
            ))

        previous = previous_files.get(normalized)
        if previous is not None and previous.size == size and previous.modified_ns == modified_ns and not stat_failed:
            counters.files_reused += 1
            if previous.classification in {
                FileClassification.EPISODE,
                FileClassification.MOVIE,
                FileClassification.SPECIAL,
                FileClassification.UNRECOGNIZED_MEDIA,
            }:
                counters.media_files_seen += 1
                return previous, stat_failed
            return None, stat_failed

        relative_parts = tuple(Path(relative).parts)
        parsed = parse_media_name(
            path,
            relative_parts=relative_parts,
            library_is_movie=root.library_kind == LibraryKind.MOVIE,
            folder_season=folder_season,
            special_kind=special_kind,
        )
        if parsed.classification not in {
            FileClassification.EPISODE,
            FileClassification.MOVIE,
            FileClassification.SPECIAL,
            FileClassification.UNRECOGNIZED_MEDIA,
        }:
            return None, stat_failed
        counters.media_files_seen += 1
        item = InventoryFile(
            str(path),
            relative,
            normalized,
            size,
            modified_ns,
            parsed.classification,
            parsed.season_number,
            parsed.episode_numbers,
            parsed.special_kind,
            parsed.absolute_episode_numbers,
        )
        if parsed.classification == FileClassification.UNRECOGNIZED_MEDIA:
            diagnostics.append(ScanDiagnostic(
                DiagnosticCode.UNRECOGNIZED_MEDIA,
                root.label,
                relative,
                message="A media file was retained without an inferred episode identity.",
            ))
        return item, stat_failed

    @staticmethod
    def _add_file(builder: _ItemBuilder, item: InventoryFile, parent: Path) -> None:
        if item.classification == FileClassification.MOVIE:
            builder.movie_files.append(item)
        elif item.classification == FileClassification.SPECIAL:
            kind = item.special_kind or SpecialKind.SPECIAL
            builder.specials.setdefault(kind, []).append(item)
            builder.special_paths.setdefault(kind, str(parent))
        elif item.classification == FileClassification.EPISODE and item.season_number is not None:
            builder.seasons.setdefault(item.season_number, []).append(item)
            builder.season_paths.setdefault(item.season_number, str(parent))
        else:
            builder.unrecognized.append(item)

    @staticmethod
    def _freeze_item(root: LibraryRoot, builder: _ItemBuilder) -> InventoryLibraryItem | None:
        path = str(builder.item_path)
        normalized = normalize_windows_path(path)
        seasons = tuple(
            InventorySeason(number, builder.season_paths[number], tuple(_sort_files(files)))
            for number, files in sorted(builder.seasons.items())
        )
        specials = tuple(
            InventorySpecialGroup(kind, builder.special_paths[kind], tuple(_sort_files(files)))
            for kind, files in sorted(builder.specials.items(), key=lambda pair: pair[0].value)
        )
        digest = hashlib.sha256(f"{root.library_kind.value}|{normalized}".encode("utf-8")).hexdigest()[:24]
        return InventoryLibraryItem(
            item_id=f"filesystem:{digest}",
            root_label=root.label,
            library_kind=root.library_kind,
            path=path,
            normalized_path=normalized,
            title=builder.item_title,
            year=extract_year(builder.item_title),
            seasons=seasons,
            specials=specials,
            movie_files=tuple(_sort_files(builder.movie_files)),
            unrecognized_media=tuple(_sort_files(builder.unrecognized)),
        )

    def _entries(
        self,
        path: Path,
        root: LibraryRoot,
        relative: str,
        diagnostics: list[ScanDiagnostic],
    ) -> tuple[list[os.DirEntry], bool]:
        try:
            with self._scandir(str(path)) as iterator:
                entries = list(iterator)
            entries.sort(key=lambda entry: (entry.name.casefold(), entry.name))
            return entries, False
        except (PermissionError, OSError) as exc:
            diagnostics.append(self._entry_diagnostic(root, relative, exc))
            return [], True

    @staticmethod
    def _claim_path(
        normalized: str,
        root: LibraryRoot,
        relative: str,
        diagnostics: list[ScanDiagnostic],
        seen_paths: set[str],
        counters: _Counters,
    ) -> bool:
        if normalized in seen_paths:
            counters.duplicate_paths_skipped += 1
            diagnostics.append(ScanDiagnostic(
                DiagnosticCode.DUPLICATE_PATH_SKIPPED,
                root.label,
                relative,
                message="A duplicate case-insensitive path was skipped.",
            ))
            return False
        seen_paths.add(normalized)
        return True

    @staticmethod
    def _entry_diagnostic(root: LibraryRoot, relative: str, exc: OSError) -> ScanDiagnostic:
        return ScanDiagnostic(
            DiagnosticCode.ENTRY_INACCESSIBLE,
            root.label,
            relative,
            type(exc).__name__,
            "A directory entry could not be read; other inventory results were retained.",
        )

    @staticmethod
    def _is_canceled(token: Cancellation | None) -> bool:
        return token is not None and token.is_cancelled()

    @staticmethod
    def _canceled_root(root: LibraryRoot) -> RootInventory:
        return RootInventory(root, RootScanStatus.CANCELED, diagnostics=(ScanDiagnostic(
            DiagnosticCode.SCAN_CANCELED, root.label, message="The inventory scan was canceled.",
        ),))


def _relative_path(path: Path, parent: Path) -> str:
    try:
        return str(path.relative_to(parent))
    except ValueError:
        return path.name


def _sort_files(files: list[InventoryFile]) -> list[InventoryFile]:
    return sorted(files, key=lambda item: (item.normalized_path, item.path))


def _sort_items(items: list[InventoryLibraryItem]) -> list[InventoryLibraryItem]:
    return sorted(items, key=lambda item: (item.normalized_path, item.path))


def _sort_diagnostics(diagnostics: list[ScanDiagnostic]) -> list[ScanDiagnostic]:
    return sorted(diagnostics, key=lambda item: (item.root_label.casefold(), item.relative_path.casefold(), item.code.value))


def _is_directory_mode(mode: int) -> bool:
    import stat

    return stat.S_ISDIR(mode)


def _is_link_or_junction(entry: os.DirEntry, path: Path) -> bool:
    if entry.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is None:
        return False
    try:
        return bool(is_junction())
    except OSError:
        return True
