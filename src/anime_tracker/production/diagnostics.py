from __future__ import annotations

import json
import platform
import sqlite3
from contextlib import closing
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

from PySide6 import __version__ as pyside_version

from ..modernization.backup import sqlite_integrity_check
from .profile import ProductionProfile
from ..runtime import APP_VERSION,BUILD_IDENTIFIER


class DiagnosticsReporter:
    def __init__(self,profile:ProductionProfile,*,version=APP_VERSION)->None:self.profile=profile;self.version=version

    def health(self,*,local_only=False)->dict:
        bootstrap=self.profile.load_bootstrap();database=self.profile.database_path
        if not database.is_file():return {"version":self.version,"profile_state":"NOT_MIGRATED","database_integrity":"unavailable","media_safety":"READ_ONLY","storage_checker_isolation":"ENFORCED"}
        with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro",uri=True)) as connection:
            schema=max(row[0] for row in connection.execute("SELECT version FROM schema_migrations"));counts={"active_titles":connection.execute("SELECT count(*) FROM tracked_media WHERE archived_at IS NULL").fetchone()[0],"archived_records":connection.execute("SELECT count(*) FROM archived_legacy_records").fetchone()[0],"open_reviews":connection.execute("SELECT count(*) FROM review_cases WHERE state IN ('OPEN','ACKNOWLEDGED')").fetchone()[0],"pending_notifications":connection.execute("SELECT count(*) FROM notification_outbox WHERE status IN ('PENDING','RETRY_WAIT','CLAIMED')").fetchone()[0],"failed_notifications":connection.execute("SELECT count(*) FROM notification_outbox WHERE status='FAILED_PERMANENT'").fetchone()[0]}
            last_scan=_scalar(connection,"SELECT completed_at FROM inventory_snapshots WHERE complete=1 ORDER BY completed_at DESC LIMIT 1")
            last_run=_row(connection,"SELECT status,completed_at,refresh_success,refresh_failed,inventory_result FROM scheduled_run_results ORDER BY completed_at DESC LIMIT 1")
            credentials=[{"channel_purpose":row[0],"provider":row[1],"configured":bool(row[2]),"enabled":bool(row[3])} for row in connection.execute("SELECT channel_purpose,provider,secret_present,enabled FROM credential_references")]
            errors=Counter(row[0] for row in connection.execute("SELECT last_error_type FROM notification_outbox WHERE last_error_type<>''"))
        backups=sorted((item for item in self.profile.backups_dir.iterdir() if item.is_dir()),reverse=True) if self.profile.backups_dir.exists() else []
        value={"version":self.version,"schema_version":schema,"profile_state":bootstrap.get("migration_state"),"cutover_state":bootstrap.get("cutover_state"),"production_profile_path":str(self.profile.root) if local_only else "Production Profile","database_integrity":sqlite_integrity_check(database),"counts":counts,"last_backup":backups[0].name if backups else "none","last_anilist_refresh":bootstrap.get("initial_anilist_baseline_at","never"),"cache_state":"available" if (self.profile.cache_dir/"anilist").exists() else "missing","last_jellyfin_scan":last_scan or "never","inventory_completeness":"COMPLETE" if last_scan else "NO_COMPLETE_SNAPSHOT","credentials":credentials,"scheduled_task_status":"NOT_INSTALLED_OR_UNVERIFIED","last_scheduled_run":last_run,"recent_error_types":dict(errors),"storage_checker_isolation":"ENFORCED","media_safety":"READ_ONLY","notifications_stage":bootstrap.get("notifications_stage",1)}
        value["build_identifier"]=BUILD_IDENTIFIER
        return value

    def write_support_report(self,path:Path)->Path:
        value=self.health(local_only=False);value["environment"]={"os":platform.system()+" "+platform.release(),"python":platform.python_version(),"pyside":pyside_version};value["generated_at"]=datetime.now(timezone.utc).isoformat();value["privacy"]={"full_paths":False,"credential_values":False,"computer_name":False,"user_name":False,"stack_traces":False};Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_text(json.dumps(value,indent=2,default=str),encoding="utf-8");return Path(path)


def _scalar(connection,sql):
    row=connection.execute(sql).fetchone();return row[0] if row else None
def _row(connection,sql):
    row=connection.execute(sql).fetchone();return dict(zip(("status","completed_at","refresh_success","refresh_failed","inventory_result"),row)) if row else None
