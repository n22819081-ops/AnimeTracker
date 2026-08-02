from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from pathlib import Path

from ..modernization.backup import build_manifest,sha256_file,sqlite_integrity_check,sqlite_online_backup,verify_manifest
from ..runtime import APP_VERSION,PROJECT_PRODUCTION_PROFILE
from .credentials import DpapiCredentialStore
from .profile import ProductionProfile


class AdoptionError(RuntimeError):pass


@dataclass(frozen=True)
class AdoptionResult:
    adopted:bool
    source_retained:bool
    target:str
    backup_reference:str
    integrity:str
    foreign_key_violations:int
    schema_version:int
    counts:dict[str,int]
    copied_files:int
    credential_state:str
    warnings:tuple[str,...]=()


def detect_project_profile(path:Path|None=None)->Path|None:
    value=Path(path or PROJECT_PRODUCTION_PROFILE)
    return value if (value/"data"/"anime_tracker_modern.db").is_file() else None


class ProfileAdoptionService:
    """Copies and verifies an existing profile; it never moves or deletes the source."""
    def __init__(self,source:ProductionProfile,target:ProductionProfile)->None:
        self.source=source;self.target=target

    def preview(self)->dict:
        return {"source":str(self.source.root),"target":str(self.target.root),"source_retained":True,"requires_confirmation":True,"available":self.source.database_path.is_file() and not self.target.database_path.exists()}

    def adopt(self,*,approved:bool)->AdoptionResult:
        if not approved:raise PermissionError("Profile adoption requires explicit confirmation.")
        source=self.source.root.resolve();target=self.target.root.resolve(strict=False)
        if source==target or source in target.parents:raise AdoptionError("Adoption target must be separate from the source profile.")
        if not self.source.database_path.is_file():raise AdoptionError("The source profile database is unavailable.")
        if target.exists() and any(target.iterdir()):raise AdoptionError("The target profile is not empty.")
        expected=self._database_facts(self.source.database_path);backup=self._create_forensic_backup(expected)
        staging=target.parent/f".{target.name}.adoption-{uuid.uuid4().hex}.tmp"
        try:
            staging.mkdir(parents=True);copied=self._copy_profile(staging,backup/"anime_tracker_modern.db")
            staged=ProductionProfile(staging);facts=self._database_facts(staged.database_path)
            self._verify_facts(expected,facts);credential_state,warnings=self._verify_credentials(staged)
            record={"application_version":APP_VERSION,"adopted_at":datetime.now(timezone.utc).isoformat(),"source_location":str(source),"source_retained":True,"backup_reference":backup.name,"verification":{"integrity":facts["integrity"],"foreign_key_violations":facts["foreign_key_violations"],"schema_version":facts["schema_version"],"counts":facts["counts"],"credential_state":credential_state},"warnings":warnings}
            staged.diagnostics_dir.mkdir(parents=True,exist_ok=True);(staged.diagnostics_dir/"profile-adoption.json").write_text(json.dumps(record,indent=2),encoding="utf-8")
            bootstrap=staged.load_bootstrap();bootstrap.update({"adoption_state":"ADOPTED_VERIFIED","adopted_at":record["adopted_at"],"notifications_stage":min(int(bootstrap.get("notifications_stage",1)),1),"private_notifications_enabled":False,"shared_notifications_enabled":False,"migration_version":APP_VERSION});staged.save_bootstrap(bootstrap)
            if target.exists():target.rmdir()
            os.replace(staging,target)
            return AdoptionResult(True,True,str(target),backup.name,facts["integrity"],facts["foreign_key_violations"],facts["schema_version"],facts["counts"],copied,credential_state,tuple(warnings))
        except Exception:
            shutil.rmtree(staging,ignore_errors=True);raise

    def _create_forensic_backup(self,expected:dict)->Path:
        stamp=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S");backup_root=self.target.root.parent/"AnimeTracker Adoption Backups";final=backup_root/f"{stamp}-pre-adoption";temporary=backup_root/f".{final.name}.{uuid.uuid4().hex}.tmp";temporary.mkdir(parents=True)
        try:
            database=temporary/"anime_tracker_modern.db";sqlite_online_backup(self.source.database_path,database)
            for source,name in ((self.source.bootstrap_path,"bootstrap.json"),(self.source.settings_path,"settings.json")):
                if source.is_file():shutil.copy2(source,temporary/name)
            metadata={"created_at":datetime.now(timezone.utc).isoformat(),"reason":"PRE_PROFILE_ADOPTION","application_version":APP_VERSION,"schema_version":expected["schema_version"],"database_sha256":sha256_file(database),"integrity":sqlite_integrity_check(database),"source_retained":True}
            (temporary/"backup_metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8");manifest=build_manifest(temporary,[item for item in temporary.iterdir() if item.is_file()]);(temporary/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
            if verify_manifest(temporary,manifest):raise AdoptionError("Pre-adoption backup manifest verification failed.")
            final.parent.mkdir(parents=True,exist_ok=True);os.replace(temporary,final);return final
        except Exception:
            shutil.rmtree(temporary,ignore_errors=True);raise

    def _copy_profile(self,staging:Path,database_snapshot:Path)->int:
        copied=0
        for path in self.source.root.rglob("*"):
            relative=path.relative_to(self.source.root)
            if relative.parts[:2]==("execution","locks") or path==self.source.database_path:continue
            if path.is_symlink():raise AdoptionError("Profile adoption refuses symbolic links.")
            destination=staging/relative
            if path.is_dir():destination.mkdir(parents=True,exist_ok=True)
            elif path.is_file():destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,destination);copied+=1
        database=staging/"data"/"anime_tracker_modern.db";database.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(database_snapshot,database);copied+=1
        if sha256_file(database)!=sha256_file(database_snapshot):raise AdoptionError("Adopted database hash verification failed.")
        return copied

    @staticmethod
    def _database_facts(path:Path)->dict:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True)) as connection:
            counts={"active_titles":connection.execute("SELECT count(*) FROM tracked_media WHERE archived_at IS NULL").fetchone()[0],"archived_records":connection.execute("SELECT count(*) FROM archived_legacy_records").fetchone()[0],"baseline_rows":connection.execute("SELECT count(*) FROM shared_announcement_baselines_v2").fetchone()[0],"review_cases":connection.execute("SELECT count(*) FROM review_cases WHERE state IN ('OPEN','ACKNOWLEDGED')").fetchone()[0],"mappings":connection.execute("SELECT count(*) FROM media_server_mappings").fetchone()[0],"rejections":connection.execute("SELECT count(*) FROM rejected_match_decisions").fetchone()[0],"candidates":connection.execute("SELECT count(*) FROM server_match_candidates").fetchone()[0],"outbox":connection.execute("SELECT count(*) FROM notification_outbox").fetchone()[0]}
            return {"integrity":connection.execute("PRAGMA integrity_check").fetchone()[0],"foreign_key_violations":len(connection.execute("PRAGMA foreign_key_check").fetchall()),"schema_version":max(row[0] for row in connection.execute("SELECT version FROM schema_migrations")),"counts":counts}

    @staticmethod
    def _verify_facts(expected:dict,actual:dict)->None:
        if actual["integrity"]!="ok" or actual["foreign_key_violations"]:raise AdoptionError("Adopted database validation failed.")
        if actual["schema_version"]!=expected["schema_version"] or actual["counts"]!=expected["counts"]:raise AdoptionError("Adopted profile facts differ from the source.")

    @staticmethod
    def _verify_credentials(profile:ProductionProfile)->tuple[str,list[str]]:
        warnings=[];failed=[];store=DpapiCredentialStore(profile.credentials_dir)
        with closing(sqlite3.connect(profile.database_path)) as connection:
            rows=connection.execute("SELECT reference_id,channel_purpose,secret_present FROM credential_references").fetchall()
            for reference,purpose,present in rows:
                if not present:continue
                try:secret=store.retrieve_secret(reference);valid=secret.reveal().startswith("https://");del secret
                except Exception:valid=False
                if not valid:failed.append(reference);warnings.append(f"{purpose} credential requires re-entry after relocation.")
            if failed:
                connection.executemany("UPDATE credential_references SET secret_present=0,enabled=0 WHERE reference_id=?",((value,) for value in failed));connection.commit()
        return ("VERIFIED" if not failed else "REENTRY_REQUIRED"),warnings
