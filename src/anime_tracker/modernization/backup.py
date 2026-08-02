from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def sqlite_online_backup(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("SQLite backup destination must differ from its source.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def sqlite_integrity_check(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def build_manifest(base_dir: Path, files: Iterable[Path]) -> dict[str, object]:
    entries = []
    for path in sorted({Path(item).resolve() for item in files}):
        if not path.is_file():
            raise FileNotFoundError(path)
        entries.append(
            {
                "path": path.relative_to(base_dir.resolve()).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "format_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": entries,
    }


def write_manifest(base_dir: Path, files: Iterable[Path], destination: Path) -> dict[str, object]:
    manifest = build_manifest(base_dir, files)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def verify_manifest(base_dir: Path, manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for entry in manifest.get("files", []):
        path = base_dir / str(entry["path"])
        if not path.is_file():
            errors.append(f"missing:{entry['path']}")
        elif path.stat().st_size != int(entry["size"]):
            errors.append(f"size:{entry['path']}")
        elif sha256_file(path) != str(entry["sha256"]):
            errors.append(f"sha256:{entry['path']}")
    return errors


@dataclass(frozen=True)
class BackupPoint:
    path: Path
    created_at: datetime


def plan_backup_retention(backups: Iterable[BackupPoint], now: datetime | None = None) -> dict[str, list[Path]]:
    """Return a non-destructive keep/review plan; this function never deletes files."""
    current = now or datetime.now(timezone.utc)
    ordered = sorted(backups, key=lambda item: item.created_at, reverse=True)
    keep: set[Path] = {item.path for item in ordered[:10]}

    daily_seen: set[tuple[int, int]] = set()
    weekly_seen: set[tuple[int, int]] = set()
    for item in ordered:
        age = current - item.created_at
        if age <= timedelta(days=14):
            key = (item.created_at.year, item.created_at.timetuple().tm_yday)
            if key not in daily_seen:
                keep.add(item.path)
                daily_seen.add(key)
        if age <= timedelta(weeks=12):
            iso = item.created_at.isocalendar()
            key = (iso.year, iso.week)
            if key not in weekly_seen:
                keep.add(item.path)
                weekly_seen.add(key)

    return {
        "keep": [item.path for item in ordered if item.path in keep],
        "eligible_for_review": [item.path for item in ordered if item.path not in keep],
    }
