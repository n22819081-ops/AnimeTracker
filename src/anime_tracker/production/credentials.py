from __future__ import annotations

import ctypes
import json
import sqlite3
import uuid
from contextlib import closing
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from ..notifications_v2.credentials import SecretValue
from .profile import ProductionProfile


PRIVATE_REFERENCE = "anime-tracker/production/private-discord"
SHARED_REFERENCE = "anime-tracker/production/shared-discord"


class Protector(Protocol):
    def protect(self, value: bytes) -> bytes: ...
    def unprotect(self, value: bytes) -> bytes: ...


class WindowsDpapiProtector:
    class DATA_BLOB(ctypes.Structure): _fields_=[("cbData",wintypes.DWORD),("pbData",ctypes.POINTER(ctypes.c_byte))]

    @classmethod
    def _blob(cls,value:bytes):
        buffer=ctypes.create_string_buffer(value); return cls.DATA_BLOB(len(value),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte))),buffer

    def protect(self,value:bytes)->bytes:
        source,source_buffer=self._blob(value); output=self.DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source),"Anime Tracker",None,None,None,0,ctypes.byref(output)): raise ctypes.WinError()
        try:return ctypes.string_at(output.pbData,output.cbData)
        finally:ctypes.windll.kernel32.LocalFree(output.pbData)

    def unprotect(self,value:bytes)->bytes:
        source,source_buffer=self._blob(value); output=self.DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source),None,None,None,None,0,ctypes.byref(output)): raise ctypes.WinError()
        try:return ctypes.string_at(output.pbData,output.cbData)
        finally:ctypes.windll.kernel32.LocalFree(output.pbData)


class DpapiCredentialStore:
    def __init__(self,directory:Path,protector:Protector|None=None)->None:
        self.directory=Path(directory); self.protector=protector or WindowsDpapiProtector(); self.directory.mkdir(parents=True,exist_ok=True)

    def _path(self,reference:str)->Path:
        import hashlib
        return self.directory/(hashlib.sha256(reference.encode("utf-8")).hexdigest()+".dpapi")

    def store_secret(self,reference:str,value:str)->None:
        if not reference or not value:raise ValueError("Credential reference and value are required.")
        self._path(reference).write_bytes(self.protector.protect(value.encode("utf-8")))

    def retrieve_secret(self,reference:str)->SecretValue:
        path=self._path(reference)
        if not path.is_file():raise KeyError(f"Credential reference not found: {reference}")
        return SecretValue(self.protector.unprotect(path.read_bytes()).decode("utf-8"))

    def delete_secret(self,reference:str)->None:self._path(reference).unlink(missing_ok=True)
    def secret_exists(self,reference:str)->bool:return self._path(reference).is_file()
    def list_references(self)->tuple[str,...]:return ()


def migrate_legacy_credentials(profile:ProductionProfile,legacy_config:Path,*,approved:bool,store:DpapiCredentialStore|None=None)->dict:
    if not approved:raise PermissionError("Credential migration requires explicit approval.")
    profile.initialize_directories(); store=store or DpapiCredentialStore(profile.credentials_dir)
    config=json.loads(Path(legacy_config).read_text(encoding="utf-8"))
    channels=(("PRIVATE_TRACKER",PRIVATE_REFERENCE,str(config.get("discord_webhook_url") or "")),("SHARED_ANNOUNCEMENT",SHARED_REFERENCE,str(config.get("shared_discord_webhook_url") or "")))
    stored=[]; now=datetime.now(timezone.utc).isoformat()
    try:
        for purpose,reference,value in channels:
            if not value:continue
            if not value.startswith("https://"):raise ValueError(f"{purpose} credential is not an HTTPS webhook.")
            store.store_secret(reference,value); stored.append((purpose,reference))
        with closing(sqlite3.connect(profile.database_path)) as connection:
            for purpose,reference in stored:
                identifier=store._path(reference).name
                connection.execute("INSERT OR REPLACE INTO credential_references(reference_id,profile_id,channel_purpose,provider,credential_identifier,secret_present,enabled,created_at,updated_at) VALUES(?,?,?,?,?,1,0,?,?)",(reference,"production",purpose,"WINDOWS_DPAPI",identifier,now,now))
                connection.execute("INSERT INTO credential_migration_audit(audit_id,channel_purpose,credential_reference,provider,secret_present,migrated_at,legacy_config_retained) VALUES(?,?,?,?,1,?,1)",(f"credential-{uuid.uuid4().hex}",purpose,reference,"WINDOWS_DPAPI",now))
            connection.commit()
    except Exception:
        for _,reference in stored:store.delete_secret(reference)
        raise
    bootstrap=profile.load_bootstrap();bootstrap["credential_migration_state"]="MIGRATED_DISABLED";profile.save_bootstrap(bootstrap)
    return {"migrated_references":[reference for _,reference in stored],"private_present":store.secret_exists(PRIVATE_REFERENCE),"shared_present":store.secret_exists(SHARED_REFERENCE),"legacy_config_retained":Path(legacy_config).is_file(),"delivery_enabled":False}
