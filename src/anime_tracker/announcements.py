from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

from .path_utils import normalize_windows_path

LOGGER = logging.getLogger(__name__)
SILENT_MESSAGE_FLAG = 1 << 12
SEASON_PATTERN = re.compile(r"^(?:season\s*|s)?0*(\d{1,3})$", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"^(.*?)\s*\((19\d{2}|20\d{2}|21\d{2})\)\s*$")


class LibraryInventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotItem:
    item_type: str
    normalized_path: str
    parent_normalized_path: str
    title: str
    year: int | None = None
    season_number: int | None = None
    original_path: str = ""


@dataclass(frozen=True)
class LibraryChange:
    change_type: str
    item_type: str
    title: str
    year: int | None = None
    seasons: tuple[int, ...] = ()
    custom_display: str = ""

    @property
    def display_text(self) -> str:
        if self.custom_display:
            return self.custom_display
        if self.item_type == "SEASON":
            return f"{self.title} — {format_seasons(self.seasons)}"
        suffix = "TV Show" if self.item_type == "TV_SHOW" else "Movie"
        return f"{self.title}{f' ({self.year})' if self.year else ''} — {suffix}"


def parse_folder_name(name: str) -> tuple[str, int | None]:
    match = YEAR_PATTERN.match(name.strip())
    return (match.group(1).strip(), int(match.group(2))) if match else (name.strip(), None)


def parse_season_number(name: str) -> int | None:
    match = SEASON_PATTERN.match(name.strip())
    return int(match.group(1)) if match else None


def build_library_snapshot(tv_root: str, movie_root: str) -> list[SnapshotItem]:
    roots = ((tv_root, "TV_SHOW"), (movie_root, "MOVIE"))
    items: list[SnapshotItem] = []
    for raw_root, item_type in roots:
        root = Path(raw_root)
        if not raw_root or not root.exists() or not root.is_dir():
            raise LibraryInventoryError(f"Jellyfin {item_type.replace('_', ' ').title()} root is unavailable: {raw_root or '(not configured)'}")
        try:
            entries = list(root.iterdir())
        except OSError as exc:
            raise LibraryInventoryError(f"Jellyfin root could not be read: {raw_root} ({type(exc).__name__})") from exc
        for entry in entries:
            try:
                is_directory = entry.is_dir()
            except OSError as exc:
                raise LibraryInventoryError(f"Jellyfin folder could not be inspected: {entry.name} ({type(exc).__name__})") from exc
            if not is_directory:
                continue
            title, year = parse_folder_name(entry.name)
            normalized = normalize_windows_path(str(entry))
            items.append(SnapshotItem(item_type, normalized, "", title, year, None, str(entry)))
            if item_type != "TV_SHOW":
                continue
            try:
                children = list(entry.iterdir())
            except OSError as exc:
                raise LibraryInventoryError(f"Jellyfin show folder could not be read: {entry.name} ({type(exc).__name__})") from exc
            for child in children:
                try:
                    season = parse_season_number(child.name) if child.is_dir() else None
                except OSError as exc:
                    raise LibraryInventoryError(f"Jellyfin season folder could not be inspected: {child.name} ({type(exc).__name__})") from exc
                if season is not None:
                    items.append(SnapshotItem("SEASON", normalize_windows_path(str(child)), normalized, title, year, season, str(child)))
    return items


def detect_changes(previous: Iterable[SnapshotItem], current: Iterable[SnapshotItem]) -> list[LibraryChange]:
    old = {item.normalized_path: item for item in previous}
    new = {item.normalized_path: item for item in current}
    changes: list[LibraryChange] = []
    added_shows = {path for path, item in new.items() if item.item_type == "TV_SHOW" and path not in old}
    removed_shows = {path for path, item in old.items() if item.item_type == "TV_SHOW" and path not in new}
    for change_type, source, other, show_paths in (
        ("added", new, old, added_shows),
        ("removed", old, new, removed_shows),
    ):
        season_groups: dict[tuple[str, str, int | None], list[int]] = {}
        for path, item in source.items():
            if path in other:
                continue
            if item.item_type == "SEASON":
                if item.parent_normalized_path in show_paths:
                    continue
                season_groups.setdefault((item.parent_normalized_path, item.title, item.year), []).append(item.season_number or 0)
            else:
                changes.append(LibraryChange(change_type, item.item_type, item.title, item.year))
        for (_parent, title, year), seasons in season_groups.items():
            changes.append(LibraryChange(change_type, "SEASON", title, year, tuple(sorted(seasons))))
    return sorted(changes, key=lambda item: (item.change_type, item.item_type, item.title.casefold(), item.seasons))


def format_seasons(seasons: Iterable[int]) -> str:
    values = sorted(set(seasons))
    if len(values) == 1:
        return f"Season {values[0]}"
    if values == list(range(values[0], values[-1] + 1)):
        return f"Seasons {values[0]}–{values[-1]}"
    if len(values) == 2:
        return f"Seasons {values[0]} and {values[1]}"
    return "Seasons " + ", ".join(str(value) for value in values[:-1]) + f", and {values[-1]}"


def default_selected(change: LibraryChange, announce_additions: bool, announce_removals: bool) -> bool:
    return announce_additions if change.change_type == "added" else announce_removals


def announcement_review_required(changes: Iterable[LibraryChange], manual_items: Iterable[object]) -> bool:
    return bool(list(changes) or list(manual_items))


def build_discord_messages(changes: Iterable[LibraryChange], max_length: int = 1900) -> list[str]:
    selected = list(changes)
    sections: list[tuple[str, list[str]]] = []
    additions = [item for item in selected if item.change_type == "added"]
    removals = [item for item in selected if item.change_type == "removed"]
    if additions:
        tv = [f"- {item.display_text}" for item in additions if item.item_type in {"TV_SHOW", "SEASON", "TV_EPISODE"}]
        movies = [f"- {item.title}{f' ({item.year})' if item.year else ''}" for item in additions if item.item_type == "MOVIE"]
        lines = (["TV Shows"] + tv if tv else []) + (["Movies"] + movies if movies else [])
        sections.append(("New on Jellyfin", lines))
    if removals:
        sections.append(("Removed from Jellyfin", [f"- {item.display_text}" for item in removals]))
    messages: list[str] = []
    for heading, lines in sections:
        current = heading
        for line in lines:
            candidate = f"{current}\n{line}"
            if len(candidate) > max_length and current != heading:
                messages.append(current)
                current = f"{heading} (continued)\n{line}"
            else:
                current = candidate
        messages.append(current)
    return messages


def send_silent_announcements(
    webhook_url: str,
    changes: Iterable[LibraryChange],
    send_silently: bool = True,
    timeout: int = 15,
) -> bool:
    messages = build_discord_messages(changes)
    if not webhook_url.strip() or not messages:
        return False
    try:
        for content in messages:
            payload = {"content": content, "allowed_mentions": {"parse": []}}
            if send_silently:
                payload["flags"] = SILENT_MESSAGE_FLAG
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
        return True
    except requests.RequestException as exc:
        LOGGER.warning("Shared Discord announcement failed without exposing webhook; error type: %s", type(exc).__name__)
        return False


def send_reviewed_batch(
    database,
    webhook_url: str,
    selected: Iterable[LibraryChange],
    current: Iterable[SnapshotItem],
    sender=send_silent_announcements,
    send_silently: bool = True,
    manual_queue_ids: Iterable[int] = (),
) -> bool:
    chosen = list(selected)
    if not chosen or not sender(webhook_url, chosen, send_silently):
        return False
    database.commit_announcement_send(list(current), list(manual_queue_ids))
    return True


def shared_announcements_apply_to_scan(silent: bool) -> bool:
    return not silent


def captured_at() -> str:
    return datetime.now(timezone.utc).isoformat()
