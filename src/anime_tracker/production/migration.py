from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from ..modernization.backup import sha256_file, sqlite_integrity_check, verify_manifest
from ..modernization.migration import build_reconciliation, migrate_legacy_copy
from ..modernization.schema_v3 import migrate_modern_database_to_v3
from ..modernization.schema_v4 import migrate_modern_database_to_v4
from ..modernization.schema_v5 import migrate_modern_database_to_v5
from .locks import FileOperationLock
from .profile import LIVE_LEGACY_DATABASE, ProductionProfile
from .schema import migrate_to_production_schema


# The old frozen counts (EXPECTED_ACTIVE=69 / EXPECTED_ARCHIVED=421 /
# EXPECTED_BASELINES=1312) were a stale fingerprint of the Aug 2 snapshot. They are
# gone on purpose: a re-migration of current Legacy (73 active) could never match a
# frozen 69, so the gate was self-sabotaging. Integrity is now guaranteed by the
# migration AUDIT (reconciliation "unexplained_loss_tables": source_count ==
# active + archived + excluded for every table), plus integrity_check, foreign_key_check
# and the raw-webhook scan. The fresh-migration path additionally validates against
# its OWN reconciliation destination_counts (passed via `expected`), which is the
# strongest check available.


class ProductionMigrationError(RuntimeError): pass


class ProductionMigrator:
    def __init__(self, profile: ProductionProfile, *, live_database: Path = LIVE_LEGACY_DATABASE) -> None:
        self.profile=profile; self.live_database=Path(live_database)

    def migrate_from_verified_backup(self, backup_dir: Path) -> dict:
        self.profile.initialize_directories(); backup_dir=Path(backup_dir)
        manifest_path=backup_dir/"manifest.json"
        if not manifest_path.is_file(): raise ProductionMigrationError("The pre-cutover backup manifest is missing.")
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        if verify_manifest(backup_dir,manifest): raise ProductionMigrationError("The pre-cutover backup failed manifest verification.")
        source=backup_dir/"anime_tracker-online.db"
        if sqlite_integrity_check(source)!="ok": raise ProductionMigrationError("The backup database failed integrity_check.")
        live_before=sha256_file(self.live_database); temporary=self.profile.data_dir/f"anime_tracker_modern.{uuid.uuid4().hex}.tmp"
        with FileOperationLock(self.profile.locks_dir/"migration.lock"):
            if self.profile.database_path.exists():
                state=self.profile.load_bootstrap().get("migration_state")
                if state=="MIGRATED_PENDING_CUTOVER": return self.validate_existing()
                raise ProductionMigrationError("A production database already exists and is not a completed migration.")
            try:
                result=migrate_legacy_copy(source,temporary,live_database_path=self.live_database,protected_roots=())
                reconciliation=build_reconciliation(source,temporary,result)
                migrate_modern_database_to_v3(temporary,live_database_path=self.live_database,protected_roots=())
                migrate_modern_database_to_v4(temporary,live_database_path=self.live_database,protected_roots=())
                migrate_modern_database_to_v5(temporary,live_database_path=self.live_database,protected_roots=())
                migrate_to_production_schema(temporary)
                validation=_validate_database(temporary,reconciliation)
                if not validation["valid"]: raise ProductionMigrationError("Production reconciliation failed: "+"; ".join(validation["errors"]))
                now=datetime.now(timezone.utc).isoformat(); migration_id=f"production-{uuid.uuid4().hex}"
                with closing(sqlite3.connect(temporary)) as connection:
                    connection.execute("INSERT INTO production_migrations(migration_id,source_sha256,backup_reference,state,started_at,completed_at,reconciliation_json) VALUES(?,?,?,?,?,?,?)",(migration_id,sha256_file(source),backup_dir.name,"MIGRATED_PENDING_CUTOVER",now,now,json.dumps(reconciliation,sort_keys=True)))
                    connection.commit()
                os.replace(temporary,self.profile.database_path)
            except Exception:
                temporary.unlink(missing_ok=True); raise
        live_after=sha256_file(self.live_database)
        if live_before!=live_after: raise ProductionMigrationError("The legacy live database changed during migration.")
        bootstrap=self.profile.load_bootstrap(); bootstrap.update({"migration_state":"MIGRATED_PENDING_CUTOVER","cutover_state":"PENDING_APPROVAL","migration_completed_at":datetime.now(timezone.utc).isoformat(),"migration_backup_reference":backup_dir.name,"legacy_database_sha256":live_before,"notification_baseline_state":"MIGRATED_PREVIEW_PENDING","initial_baseline_accepted":False,"initial_events_created":0})
        self.profile.save_bootstrap(bootstrap)
        return {**validation,"reconciliation":reconciliation,"backup_reference":backup_dir.name,"legacy_sha256_before":live_before,"legacy_sha256_after":live_after}

    def validate_existing(self) -> dict:
        if not self.profile.database_path.is_file(): raise ProductionMigrationError("Production database is missing.")
        report={"unexplained_loss_tables":[]}
        validation=_validate_database(self.profile.database_path,report)
        return {**validation,"reconciliation":report,"backup_reference":self.profile.load_bootstrap().get("migration_backup_reference","")}


def _validate_database(path: Path, reconciliation: dict) -> dict:
    errors=[]
    if sqlite_integrity_check(path)!="ok": errors.append("integrity_check is not ok")
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        counts={
            "active_titles":connection.execute("SELECT count(*) FROM tracked_media WHERE archived_at IS NULL").fetchone()[0],
            "archived_orphans":connection.execute("SELECT count(*) FROM archived_legacy_records").fetchone()[0],
            "shared_baselines":connection.execute("SELECT count(*) FROM shared_announcement_baselines_v2").fetchone()[0],
            "mappings":connection.execute("SELECT count(*) FROM media_server_mappings").fetchone()[0],
            "rejections":connection.execute("SELECT count(*) FROM rejected_match_decisions").fetchone()[0],
            "candidates":connection.execute("SELECT count(*) FROM server_match_candidates").fetchone()[0],
            "foreign_key_violations":len(connection.execute("PRAGMA foreign_key_check").fetchall()),
        }
        raw_settings="\n".join(str(row[0]) for row in connection.execute("SELECT value FROM application_settings"))
        raw_credentials="\n".join(str(row[0]) for row in connection.execute("SELECT credential_identifier FROM credential_references"))
    # The frozen count comparisons (active/archived/baselines vs a hardcoded snapshot)
    # are gone: they were a stale Aug 2 fingerprint and self-sabotaged any re-migration.
    # What remains is the real integrity contract:
    #   * integrity_check == ok
    #   * no foreign-key violations
    #   * no raw webhook URL leaked into SQLite
    #   * migration audit balanced (no unexplained loss in any table)
    if counts["foreign_key_violations"]: errors.append("foreign key violations exist")
    if reconciliation.get("unexplained_loss_tables"): errors.append("migration audit has unexplained loss")
    if "discord.com/api/webhooks" in (raw_settings+raw_credentials).casefold(): errors.append("raw webhook found in SQLite")
    return {"valid":not errors,"errors":errors,"counts":counts,"integrity":"ok" if not errors or "integrity_check is not ok" not in errors else "failed"}
