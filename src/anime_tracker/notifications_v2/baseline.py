from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class BaselineItem:
    inventory_identity: str
    item_type: str
    display_title: str
    parent_identity: str = ""
    year: int | None = None
    season_number: int | None = None
    evidence: dict | None = None


@dataclass(frozen=True)
class BaselineComparison:
    additions: tuple[BaselineItem, ...]
    removals: tuple[BaselineItem, ...]
    baseline_established: bool = False


class SharedBaselineRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def compare(self, items: Iterable[BaselineItem], *, profile_id: str = "default", complete: bool = True) -> BaselineComparison:
        current = {item.inventory_identity: item for item in items}
        with _connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM shared_announcement_baselines_v2 WHERE profile_id=? AND active=1", (profile_id,)).fetchall()
        previous = {row["inventory_identity"]: _item(row) for row in rows}
        if not previous:
            return BaselineComparison((), (), True)
        additions = tuple(current[key] for key in sorted(current.keys() - previous.keys()))
        removals = tuple(previous[key] for key in sorted(previous.keys() - current.keys())) if complete else ()
        return BaselineComparison(additions, removals)

    def accept(self, items: Iterable[BaselineItem], now: datetime, *, profile_id: str = "default", complete: bool = True) -> None:
        if not complete:
            return
        values = tuple(items)
        with _connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE shared_announcement_baselines_v2 SET active=0 WHERE profile_id=?", (profile_id,))
            for item in values:
                connection.execute(
                    """INSERT INTO shared_announcement_baselines_v2(
                       baseline_id,profile_id,inventory_identity,item_type,parent_identity,display_title,year,
                       season_number,evidence_json,accepted_at,active,legacy_source
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,1,0)
                       ON CONFLICT(profile_id,inventory_identity) DO UPDATE SET
                       item_type=excluded.item_type,parent_identity=excluded.parent_identity,
                       display_title=excluded.display_title,year=excluded.year,season_number=excluded.season_number,
                       evidence_json=excluded.evidence_json,accepted_at=excluded.accepted_at,active=1""",
                    (f"baseline-{_digest(profile_id + '|' + item.inventory_identity)}",profile_id,item.inventory_identity,item.item_type,item.parent_identity,item.display_title,item.year,item.season_number,json.dumps(item.evidence or {},sort_keys=True),now.astimezone(timezone.utc).isoformat()),
                )

    def accept_after_delivery(self, outbox_id: str, items: Iterable[BaselineItem], now: datetime, *, profile_id: str = "default") -> None:
        with _connect(self.database_path) as connection:
            row = connection.execute("SELECT status FROM notification_outbox WHERE outbox_id=?", (outbox_id,)).fetchone()
        if not row or row[0] != "DELIVERED":
            raise ValueError("Shared baseline advances only after successful delivery.")
        self.accept(items, now, profile_id=profile_id)


def _item(row: sqlite3.Row) -> BaselineItem:
    return BaselineItem(row["inventory_identity"],row["item_type"],row["display_title"],row["parent_identity"],row["year"],row["season_number"],json.loads(row["evidence_json"]))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
