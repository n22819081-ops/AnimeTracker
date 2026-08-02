from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .privacy import ensure_privacy_safe


class ManualAnnouncementRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def create_draft(self, title: str, items: Iterable[dict], now: datetime, *, profile_id: str = "default") -> str:
        grouped = tuple(dict(item) for item in items)
        ensure_privacy_safe({"title":title,"items":grouped})
        payload = json.dumps(grouped,sort_keys=True)
        key = hashlib.sha256(f"{profile_id}|{title}|{payload}".encode("utf-8")).hexdigest()
        draft_id = f"draft-{uuid.uuid4().hex}"
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO manual_announcement_drafts VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                (draft_id,None,profile_id,title,payload,"DRAFT",key,_iso(now),_iso(now)),
            )
            row = connection.execute("SELECT draft_id FROM manual_announcement_drafts WHERE deduplication_key=?",(key,)).fetchone()
            connection.commit()
        return row[0]

    def set_status(self, draft_id: str, status: str, now: datetime) -> None:
        allowed={"DRAFT","PENDING","CLAIMED","DELIVERED","FAILED","CANCELED"}
        if status not in allowed:
            raise ValueError(status)
        with closing(sqlite3.connect(self.database_path)) as connection:
            current=connection.execute("SELECT status FROM manual_announcement_drafts WHERE draft_id=?",(draft_id,)).fetchone()
            if current is None:
                raise KeyError(draft_id)
            if current[0] == "DELIVERED" and status != "DELIVERED":
                raise ValueError("Delivered manual announcements are immutable.")
            connection.execute(
                "UPDATE manual_announcement_drafts SET status=?,updated_at=?,delivered_at=? WHERE draft_id=?",
                (status,_iso(now),_iso(now) if status=="DELIVERED" else None,draft_id),
            )
            connection.commit()

    def claim_pending(self, now: datetime) -> str | None:
        with closing(sqlite3.connect(self.database_path,timeout=30)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row=connection.execute("SELECT draft_id FROM manual_announcement_drafts WHERE status='PENDING' ORDER BY created_at,draft_id LIMIT 1").fetchone()
            if row:
                connection.execute("UPDATE manual_announcement_drafts SET status='CLAIMED',updated_at=? WHERE draft_id=? AND status='PENDING'",(_iso(now),row[0]))
            connection.commit()
            return row[0] if row else None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()
