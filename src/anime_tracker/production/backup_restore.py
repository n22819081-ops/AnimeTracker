from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from ..modernization.backup import BackupPoint, build_manifest, plan_backup_retention, sha256_file, sqlite_integrity_check, sqlite_online_backup, verify_manifest
from .locks import FileOperationLock
from .profile import LIVE_LEGACY_DATABASE, ProductionProfile
from ..runtime import APP_VERSION


PROTECTED_REASONS={"PRE_MIGRATION","PRE_PRODUCTION_CUTOVER"}


class BackupError(RuntimeError):pass
class RestoreError(RuntimeError):pass


class ModernBackupManager:
    def __init__(self,profile:ProductionProfile,*,version:str=APP_VERSION)->None:self.profile=profile;self.version=version

    def create(self,reason:str)->Path:
        if not self.profile.database_path.is_file():raise BackupError("The modern production database is unavailable.")
        self.profile.backups_dir.mkdir(parents=True,exist_ok=True);stamp=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S");final=self.profile.backups_dir/f"{stamp}-{reason.casefold().replace('_','-')}";temporary=self.profile.backups_dir/f".{final.name}.{uuid.uuid4().hex}.tmp"
        with FileOperationLock(self.profile.locks_dir/"backup.lock"):
            temporary.mkdir(parents=True)
            try:
                database=temporary/"anime_tracker_modern.db";sqlite_online_backup(self.profile.database_path,database);integrity=sqlite_integrity_check(database)
                if integrity!="ok":raise BackupError("Backup integrity_check failed.")
                for source,name in ((self.profile.bootstrap_path,"bootstrap.json"),(self.profile.settings_path,"settings.json")):
                    if source.is_file():shutil.copy2(source,temporary/name)
                references=[]
                with closing(sqlite3.connect(f"file:{self.profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:
                    schema=max(row[0] for row in connection.execute("SELECT version FROM schema_migrations"));references=[{"reference_id":row[0],"channel_purpose":row[1],"provider":row[2],"secret_present":bool(row[3]),"enabled":bool(row[4])} for row in connection.execute("SELECT reference_id,channel_purpose,provider,secret_present,enabled FROM credential_references")]
                (temporary/"credential_references.json").write_text(json.dumps(references,indent=2),encoding="utf-8")
                metadata={"backup_id":f"backup-{uuid.uuid4().hex}","created_at":datetime.now(timezone.utc).isoformat(),"reason":reason,"application_version":self.version,"schema_version":schema,"database_sha256":sha256_file(database),"integrity_result":integrity,"raw_credentials_included":False}
                (temporary/"backup_metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
                files=[item for item in temporary.iterdir() if item.is_file()];manifest=build_manifest(temporary,files);(temporary/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
                if verify_manifest(temporary,manifest):raise BackupError("Backup manifest verification failed.")
                os.replace(temporary,final)
                with closing(sqlite3.connect(self.profile.database_path)) as connection:connection.execute("INSERT INTO backup_audit VALUES(?,?,?,?,?,?,?)",(metadata["backup_id"],reason,metadata["created_at"],final.name,metadata["database_sha256"],integrity,sha256_file(final/"manifest.json")));connection.commit()
                return final
            except Exception:
                shutil.rmtree(temporary,ignore_errors=True);raise

    def retention_preview(self)->dict[str,list[Path]]:
        points=[]
        for path in self.profile.backups_dir.iterdir() if self.profile.backups_dir.exists() else ():
            if not path.is_dir() or path.name.startswith("."):continue
            try:created=datetime.strptime(path.name[:15],"%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:continue
            points.append(BackupPoint(path,created))
        plan=plan_backup_retention(points)
        protected=[path for path in plan["eligible_for_review"] if any(reason.casefold().replace("_","-") in path.name for reason in PROTECTED_REASONS)]
        plan["keep"].extend(protected);plan["eligible_for_review"]=[path for path in plan["eligible_for_review"] if path not in protected]
        return plan


class ModernRestoreManager:
    def __init__(self,profile:ProductionProfile,backup_manager:ModernBackupManager|None=None)->None:self.profile=profile;self.backup_manager=backup_manager or ModernBackupManager(profile)

    def validate(self,backup:Path)->dict:
        backup=Path(backup);manifest_path=backup/"manifest.json";metadata_path=backup/"backup_metadata.json";database=backup/"anime_tracker_modern.db"
        if not manifest_path.is_file() or not metadata_path.is_file() or not database.is_file():raise RestoreError("Backup is incomplete.")
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"));errors=verify_manifest(backup,manifest)
        metadata=json.loads(metadata_path.read_text(encoding="utf-8"))
        if errors:raise RestoreError("Backup manifest verification failed.")
        if sha256_file(database)!=metadata["database_sha256"]:raise RestoreError("Backup database hash mismatch.")
        if sqlite_integrity_check(database)!="ok":raise RestoreError("Backup database integrity check failed.")
        return metadata

    def restore(self,backup:Path,*,approved:bool)->dict:
        if not approved:raise PermissionError("Restore requires explicit approval.")
        if self.profile.database_path.resolve()==LIVE_LEGACY_DATABASE.resolve():raise RestoreError("Restore cannot target the legacy database.")
        metadata=self.validate(backup);pre_restore=self.backup_manager.create("PRE_RESTORE");temporary=self.profile.data_dir/f"restore.{uuid.uuid4().hex}.tmp"
        with FileOperationLock(self.profile.locks_dir/"restore.lock"):
            shutil.copy2(Path(backup)/"anime_tracker_modern.db",temporary)
            if sqlite_integrity_check(temporary)!="ok":temporary.unlink(missing_ok=True);raise RestoreError("Restored copy failed integrity validation.")
            os.replace(temporary,self.profile.database_path)
        return {"restored":True,"backup_id":metadata["backup_id"],"pre_restore_backup":pre_restore.name,"integrity":"ok"}
