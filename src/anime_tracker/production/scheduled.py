from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from enum import Enum

from .backup_restore import ModernBackupManager
from .locks import FileOperationLock,OperationAlreadyRunning
from .operations import ProductionAniListOperations,ProductionInventoryOperations
from .profile import ProductionProfile


class ScheduledRunStatus(str,Enum):
    SUCCESS="SUCCESS";PARTIAL_SUCCESS="PARTIAL_SUCCESS";FAILED="FAILED";CANCELED="CANCELED";ALREADY_RUNNING="ALREADY_RUNNING";OFFLINE_CACHE_ONLY="OFFLINE_CACHE_ONLY"


@dataclass
class ScheduledRunResult:
    run_id:str;started_at:str;completed_at:str;status:str;refresh_success:int=0;refresh_failed:int=0;cache_hits:int=0;inventory_result:str="DISABLED";mapping_result:str="DISABLED";events_created:int=0;delivered:int=0;retry_count:int=0;permanent_failures:int=0;warnings:tuple[str,...]=()


class ScheduledCheckRunner:
    def __init__(self,profile:ProductionProfile,*,anilist=None,inventory=None,backup=None,deliver=None)->None:
        self.profile=profile;self.anilist=anilist or ProductionAniListOperations(profile);self.inventory=inventory or ProductionInventoryOperations(profile);self.backup=backup or ModernBackupManager(profile);self.deliver=deliver

    def run(self)->ScheduledRunResult:
        started=datetime.now(timezone.utc);run_id=f"scheduled-{uuid.uuid4().hex}"
        if not self.profile.database_path.is_file():
            result=ScheduledRunResult(run_id,started.isoformat(),datetime.now(timezone.utc).isoformat(),ScheduledRunStatus.FAILED.value,warnings=("The modern production database is not migrated.",));self._write_log(result);return result
        try:
            with FileOperationLock(self.profile.locks_dir/"scheduled-check.lock"):
                result=self._execute(run_id,started)
        except OperationAlreadyRunning:
            return ScheduledRunResult(run_id,started.isoformat(),datetime.now(timezone.utc).isoformat(),ScheduledRunStatus.ALREADY_RUNNING.value,warnings=("Another scheduled check holds the production lock.",))
        self._record(result);self._write_log(result);return result

    def _execute(self,run_id,started)->ScheduledRunResult:
        config=self.profile.load_bootstrap();warnings=[];refresh={"succeeded":0,"failed":0,"cache_hits":0,"state":"DISABLED"};inventory_result="DISABLED";events=delivered=retry=failed_delivery=0
        try:self.backup.create("SCHEDULED")
        except Exception as exc:warnings.append(f"Scheduled backup failed: {type(exc).__name__}")
        if config.get("anilist_refresh_enabled"):
            try:refresh=self.anilist.refresh(baseline=False)
            except Exception as exc:refresh={"succeeded":0,"failed":len(self.anilist.active_ids()),"cache_hits":0,"state":"FAILED"};warnings.append(f"AniList refresh failed: {type(exc).__name__}")
        if config.get("jellyfin_scan_enabled"):
            try:inventory_result=self.inventory.scan(confirmed=True)["status"]
            except Exception as exc:inventory_result="FAILED";warnings.append(f"Inventory scan failed: {type(exc).__name__}")
        mapping_result="RETAINED" if inventory_result!="COMPLETE" else "REVIEW_SUGGESTIONS_ONLY"
        delivery_enabled=config.get("notifications_stage",1)>=3 and (config.get("private_notifications_enabled") or config.get("shared_notifications_enabled"))
        if delivery_enabled and self.deliver:
            delivery=self.deliver();delivered=delivery.delivered;retry=delivery.retry_pending;failed_delivery=delivery.permanently_failed
        elif delivery_enabled:warnings.append("Notification delivery is enabled but no dispatcher is configured.")
        if refresh.get("state")=="OFFLINE_CACHE_ONLY":status=ScheduledRunStatus.OFFLINE_CACHE_ONLY
        elif refresh.get("failed",0) or inventory_result in {"PARTIAL","FAILED"} or warnings:status=ScheduledRunStatus.PARTIAL_SUCCESS if refresh.get("succeeded",0) or inventory_result=="COMPLETE" else ScheduledRunStatus.FAILED
        else:status=ScheduledRunStatus.SUCCESS
        return ScheduledRunResult(run_id,started.isoformat(),datetime.now(timezone.utc).isoformat(),status.value,int(refresh.get("succeeded",0)),int(refresh.get("failed",0)),int(refresh.get("cache_hits",0)),inventory_result,mapping_result,events,delivered,retry,failed_delivery,tuple(warnings))

    def _record(self,result):
        with closing(sqlite3.connect(self.profile.database_path)) as connection:connection.execute("INSERT INTO scheduled_run_results VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(result.run_id,result.started_at,result.completed_at,result.status,result.refresh_success,result.refresh_failed,result.cache_hits,result.inventory_result,result.mapping_result,result.events_created,result.delivered,result.retry_count,result.permanent_failures,json.dumps(result.warnings)));connection.commit()

    def _write_log(self,result):
        self.profile.logs_dir.mkdir(parents=True,exist_ok=True);(self.profile.logs_dir/"scheduled-check-latest.json").write_text(json.dumps(asdict(result),indent=2),encoding="utf-8")
