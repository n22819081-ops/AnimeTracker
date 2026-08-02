from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .enums import ChannelPurpose, DeliveryResultType, OutboxStatus
from .models import DeliveryResult, NotificationEvent, NotificationMessage, OutboxItem
from .privacy import ensure_privacy_safe, safe_error_summary
from .retry import retry_decision
from .templates import message_to_dict


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class NotificationOutboxRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def enqueue(
        self,
        event: NotificationEvent,
        message: NotificationMessage,
        credential_reference: str,
        *,
        suppressed_reason: str = "",
    ) -> tuple[OutboxItem, bool]:
        payload = message_to_dict(message)
        ensure_privacy_safe(payload)
        now = event.created_at or datetime.now(timezone.utc)
        suppressed_reason = suppressed_reason or self.suppression_reason(
            event, message.channel_purpose, now,
        )
        status = OutboxStatus.SUPPRESSED if suppressed_reason else OutboxStatus.PENDING
        channel_key = f"{message.channel_purpose.value}:{event.deduplication_key}"
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR IGNORE INTO notification_events_v2(
                    event_id,event_type,anilist_id,franchise_id,event_timestamp,source_transition_id,
                    previous_state,new_state,payload_json,severity,privacy_level,deduplication_key,
                    correlation_id,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.event_id,event.event_type.value,event.anilist_id,event.franchise_id,_iso(event.event_timestamp),
                    event.source_transition_id,event.previous_state,event.new_state,
                    json.dumps(dict(event.payload),sort_keys=True,default=str),event.severity.value,event.privacy_level.value,
                    event.deduplication_key,event.correlation_id,_iso(now),
                ),
            )
            stored_event_id = connection.execute(
                "SELECT event_id FROM notification_events_v2 WHERE deduplication_key=?",
                (event.deduplication_key,),
            ).fetchone()[0]
            outbox_id = f"outbox-{uuid.uuid4().hex}"
            cursor = connection.execute(
                """INSERT OR IGNORE INTO notification_outbox(
                    outbox_id,event_id,channel_purpose,credential_reference,payload_json,status,
                    attempt_count,created_at,updated_at,deduplication_key,suppression_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (outbox_id,stored_event_id,message.channel_purpose.value,credential_reference,json.dumps(payload,sort_keys=True),status.value,0,_iso(now),_iso(now),channel_key,suppressed_reason),
            )
            created = cursor.rowcount == 1
            row = connection.execute("SELECT * FROM notification_outbox WHERE deduplication_key=?", (channel_key,)).fetchone()
        return _outbox(row), created

    def suppression_reason(
        self,
        event: NotificationEvent,
        channel: ChannelPurpose,
        now: datetime,
        *,
        profile_id: str = "default",
    ) -> str:
        with self.connect() as connection:
            setting = connection.execute(
                "SELECT enabled FROM notification_channel_settings WHERE profile_id=? AND channel_purpose=?",
                (profile_id,channel.value),
            ).fetchone()
            if setting is not None and not setting["enabled"]:
                return "Channel disabled."
            event_filter = connection.execute(
                "SELECT enabled FROM notification_event_filters WHERE profile_id=? AND channel_purpose=? AND event_type=?",
                (profile_id,channel.value,event.event_type.value),
            ).fetchone()
            if event_filter is not None and not event_filter["enabled"]:
                return "Event disabled for channel."
            row = connection.execute(
                """SELECT reason FROM notification_suppressions
                   WHERE profile_id=? AND channel_purpose=? AND active=1
                     AND (anilist_id IS NULL OR anilist_id=?)
                     AND (event_type IS NULL OR event_type=?)
                     AND starts_at<=? AND (ends_at IS NULL OR ends_at>?)
                   ORDER BY starts_at DESC LIMIT 1""",
                (profile_id,channel.value,event.anilist_id,event.event_type.value,_iso(now),_iso(now)),
            ).fetchone()
        return (row["reason"] or "Notification suppressed.") if row else ""

    def save_suppression(
        self,
        suppression_id: str,
        channel: ChannelPurpose,
        starts_at: datetime,
        *,
        profile_id: str = "default",
        anilist_id: int | None = None,
        event_type: str | None = None,
        ends_at: datetime | None = None,
        reason: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO notification_suppressions VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                (suppression_id,profile_id,anilist_id,event_type,channel.value,_iso(starts_at),_iso(ends_at),1,reason),
            )

    def clear_suppression(self, suppression_id: str, now: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE notification_suppressions SET active=0,cleared_at=? WHERE suppression_id=?",
                (_iso(now),suppression_id),
            )

    def set_event_filter(
        self,
        channel: ChannelPurpose,
        event_type: str,
        enabled: bool,
        *,
        profile_id: str = "default",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO notification_event_filters VALUES(?,?,?,?)
                   ON CONFLICT(profile_id,channel_purpose,event_type) DO UPDATE SET enabled=excluded.enabled""",
                (profile_id,channel.value,event_type,int(enabled)),
            )

    def claim_batch(
        self,
        worker_id: str,
        now: datetime,
        *,
        limit: int = 100,
        lease: timedelta = timedelta(minutes=5),
    ) -> tuple[OutboxItem, ...]:
        expires = now + lease
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT outbox_id FROM notification_outbox
                   WHERE (status='PENDING' OR (status='RETRY_WAIT' AND next_attempt_at<=?)
                          OR (status='CLAIMED' AND claim_expires_at<=?))
                   ORDER BY created_at,outbox_id LIMIT ?""",
                (_iso(now), _iso(now), limit),
            ).fetchall()
            ids = [row[0] for row in rows]
            for outbox_id in ids:
                connection.execute(
                    """UPDATE notification_outbox SET status='CLAIMED',claimed_by=?,claim_expires_at=?,updated_at=?
                       WHERE outbox_id=? AND (status='PENDING' OR (status='RETRY_WAIT' AND next_attempt_at<=?)
                       OR (status='CLAIMED' AND claim_expires_at<=?))""",
                    (worker_id,_iso(expires),_iso(now),outbox_id,_iso(now),_iso(now)),
                )
            if not ids:
                return ()
            placeholders = ",".join("?" for _ in ids)
            claimed = connection.execute(
                f"SELECT * FROM notification_outbox WHERE outbox_id IN ({placeholders}) AND claimed_by=? AND status='CLAIMED' ORDER BY created_at,outbox_id",
                (*ids,worker_id),
            ).fetchall()
        return tuple(_outbox(row) for row in claimed)

    def complete(self, outbox_id: str, worker_id: str, result: DeliveryResult, now: datetime) -> OutboxItem:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM notification_outbox WHERE outbox_id=?", (outbox_id,)).fetchone()
            if row is None:
                raise KeyError(outbox_id)
            if row["status"] != "CLAIMED" or row["claimed_by"] != worker_id:
                raise PermissionError("Outbox claim ownership does not match.")
            attempt_count = int(row["attempt_count"]) + 1
            status = OutboxStatus.DELIVERED
            next_attempt = None
            delivered = now
            if result.result == DeliveryResultType.RETRYABLE_FAILURE:
                decision = retry_decision(attempt_count - 1, now, retry_after_seconds=result.retry_after_seconds)
                status = OutboxStatus.RETRY_WAIT if decision.retryable else OutboxStatus.FAILED_PERMANENT
                next_attempt = decision.next_attempt_at
                delivered = None
            elif result.result == DeliveryResultType.PERMANENT_FAILURE:
                status = OutboxStatus.FAILED_PERMANENT
                delivered = None
            elif result.result == DeliveryResultType.CANCELED:
                status = OutboxStatus.CANCELED
                delivered = None
            error = safe_error_summary(result.error_summary)
            connection.execute(
                """UPDATE notification_outbox SET status=?,attempt_count=?,next_attempt_at=?,claimed_by='',
                   claim_expires_at=NULL,updated_at=?,last_error_type=?,last_error_message=?,delivered_at=?
                   WHERE outbox_id=? AND claimed_by=? AND status='CLAIMED'""",
                (status.value,attempt_count,_iso(next_attempt),_iso(now),result.error_type,error,_iso(delivered),outbox_id,worker_id),
            )
            connection.execute(
                """INSERT INTO notification_delivery_attempts(
                    attempt_id,outbox_id,started_at,completed_at,result,http_status,retryable,error_type,
                    error_summary,response_metadata_json,worker_identity
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (f"attempt-{uuid.uuid4().hex}",outbox_id,_iso(now),_iso(now),result.result.value,result.http_status,int(result.retryable),result.error_type,error,json.dumps(dict(result.response_metadata),sort_keys=True,default=str),worker_id),
            )
            updated = connection.execute("SELECT * FROM notification_outbox WHERE outbox_id=?", (outbox_id,)).fetchone()
        return _outbox(updated)

    def cancel(self, outbox_id: str, now: datetime) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE notification_outbox SET status='CANCELED',updated_at=? WHERE outbox_id=? AND status NOT IN ('DELIVERED','FAILED_PERMANENT')", (_iso(now),outbox_id))

    def get(self, outbox_id: str) -> OutboxItem | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM notification_outbox WHERE outbox_id=?", (outbox_id,)).fetchone()
        return _outbox(row) if row else None

    def list_attempts(self, outbox_id: str) -> tuple[sqlite3.Row, ...]:
        with self.connect() as connection:
            return tuple(connection.execute("SELECT * FROM notification_delivery_attempts WHERE outbox_id=? ORDER BY started_at,attempt_id", (outbox_id,)).fetchall())


def _outbox(row: sqlite3.Row) -> OutboxItem:
    return OutboxItem(
        row["outbox_id"],row["event_id"],ChannelPurpose(row["channel_purpose"]),row["credential_reference"],
        json.loads(row["payload_json"]),OutboxStatus(row["status"]),row["attempt_count"],_dt(row["next_attempt_at"]),
        row["claimed_by"],_dt(row["claim_expires_at"]),_dt(row["created_at"]),_dt(row["updated_at"]),
        row["last_error_type"],row["last_error_message"],_dt(row["delivered_at"]),row["deduplication_key"],
    )
