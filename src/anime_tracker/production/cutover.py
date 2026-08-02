from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime,timezone

from .migration import ProductionMigrator
from .profile import ProductionProfile


CUTOVER_PHRASE="MAKE MODERN TRACKER PRIMARY"


def approve_cutover(profile:ProductionProfile,*,confirmation:str,disable_legacy_task=None)->dict:
    if confirmation!=CUTOVER_PHRASE:raise PermissionError("Production cutover requires the exact confirmation phrase.")
    validation=ProductionMigrator(profile).validate_existing()
    if not validation["valid"]:raise RuntimeError("Production database validation failed.")
    bootstrap=profile.load_bootstrap()
    if bootstrap.get("migration_state")!="MIGRATED_PENDING_CUTOVER":raise RuntimeError("Production migration is not ready for cutover.")
    now=datetime.now(timezone.utc).isoformat();legacy_changed=False
    if disable_legacy_task is not None:legacy_changed=bool(disable_legacy_task())
    bootstrap.update({"migration_state":"ACTIVE","cutover_state":"APPROVED","cutover_at":now,"legacy_task_disabled":legacy_changed});profile.save_bootstrap(bootstrap)
    with closing(sqlite3.connect(profile.database_path)) as connection:connection.execute("INSERT INTO cutover_audit VALUES(?,?,?,?,?,?,?)",(f"cutover-{uuid.uuid4().hex}","APPROVED",now,bootstrap.get("migration_version","0.8.0"),bootstrap.get("migration_backup_reference",""),int(legacy_changed),json.dumps({"legacy_database_preserved":True,"notifications_stage":bootstrap.get("notifications_stage",1)})));connection.commit()
    return {"cutover_state":"APPROVED","legacy_task_changed":legacy_changed,"legacy_preserved":True}


def rollback_to_legacy(profile:ProductionProfile,*,approved:bool,disable_modern_task=None,enable_legacy_task=None)->dict:
    if not approved:raise PermissionError("Rollback requires explicit approval.")
    modern_changed=bool(disable_modern_task()) if disable_modern_task else False;legacy_changed=bool(enable_legacy_task()) if enable_legacy_task else False
    bootstrap=profile.load_bootstrap();bootstrap.update({"cutover_state":"ROLLED_BACK","migration_state":"MIGRATED_ROLLBACK","rollback_at":datetime.now(timezone.utc).isoformat(),"scheduled_checks_enabled":False,"private_notifications_enabled":False,"shared_notifications_enabled":False});profile.save_bootstrap(bootstrap)
    return {"rolled_back":True,"modern_database_preserved":profile.database_path.is_file(),"modern_task_changed":modern_changed,"legacy_task_changed":legacy_changed,"media_restore_required":False}
