from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path

from ..domain.enums import LibraryKind
from ..normalization import normalize_title
from ..services.anilist.cache import AniListCache
from ..services.anilist.cancellation import CancellationToken
from ..services.anilist.client import AniListGraphQLClient
from ..services.anilist.service import AniListService
from ..services.server_inventory.models import LibraryRoot, RootScanStatus, ServerInventorySnapshot
from ..services.server_inventory.service import FilesystemInventoryService
from .profile import ProductionProfile


LIVE_ROOTS=(LibraryRoot("TV Library",r"I:\Jellyfin_Media\TV-SHOWs",LibraryKind.TV),LibraryRoot("Movies Library",r"I:\Jellyfin_Media\Movies",LibraryKind.MOVIE))


class ProductionAniListOperations:
    def __init__(self,profile:ProductionProfile,service:AniListService|None=None)->None:
        self.profile=profile;self.service=service or AniListService(AniListCache(profile.database_path),AniListGraphQLClient())

    def active_ids(self)->tuple[int,...]:
        with closing(sqlite3.connect(f"file:{self.profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:return tuple(row[0] for row in connection.execute("SELECT anilist_id FROM tracked_media WHERE archived_at IS NULL ORDER BY anilist_id"))

    def preview(self,ids=None)->dict:
        requested=tuple(dict.fromkeys(ids or self.active_ids()));return {"requested_ids":requested,"count":len(requested),"deduplicated":True,"archived_excluded":True,"notifications_suppressed":True}

    def refresh(self,ids=None,*,force=False,offline=False,token:CancellationToken|None=None,baseline=True)->dict:
        requested=tuple(dict.fromkeys(ids or self.active_ids()))
        if offline:
            results=tuple(self.service.get_media(item,offline=True,token=token) for item in requested)
            succeeded=sum(item.success for item in results);failed=len(results)-succeeded;cache_hits=sum(item.cache_hit for item in results);state="OFFLINE_CACHE_ONLY" if succeeded else "FAILED"
        else:
            batch=self.service.refresh_batch(requested,force_refresh=force,token=token,include_archived=False)
            results=batch.results;succeeded=batch.succeeded;failed=batch.failed;cache_hits=batch.cache_hits;state=batch.state.value
        for result in results:
            if result.success and result.updated_data:self._sync_media(result.updated_data)
        if baseline:
            bootstrap=self.profile.load_bootstrap();bootstrap["initial_anilist_baseline_state"]="ACCEPTED" if failed==0 else "PARTIAL";bootstrap["initial_anilist_baseline_at"]=datetime.now(timezone.utc).isoformat();self.profile.save_bootstrap(bootstrap)
        return {"state":state,"requested":len(requested),"succeeded":succeeded,"failed":failed,"cache_hits":cache_hits,"notifications_created":0,"failures":[{"anilist_id":item.anilist_id,"error_type":item.error_type} for item in results if not item.success]}

    def _sync_media(self,media)->None:
        now=datetime.now(timezone.utc).isoformat();cover=media.cover_images.extra_large or media.cover_images.large or media.cover_images.medium
        with closing(sqlite3.connect(self.profile.database_path)) as connection:
            connection.execute("UPDATE anilist_media SET media_format=?,season_name=?,season_year=?,episode_count=?,anilist_status=?,start_date=?,end_date=?,cover_image_url=?,page_url=?,source_updated_at=? WHERE anilist_id=?",(media.media_format.value,media.season,media.season_year,media.episode_count,media.status.value,media.start_date.isoformat() if media.start_date else "",media.end_date.isoformat() if media.end_date else "",cover,media.site_url,now,media.anilist_id))
            for kind,title in (("english",media.title.english),("romaji",media.title.romaji),("native",media.title.native),*(("synonym",item) for item in media.title.synonyms)):
                if title:connection.execute("INSERT OR REPLACE INTO media_titles(anilist_id,title_type,title,normalized_title) VALUES(?,?,?,?)",(media.anilist_id,kind,title,normalize_title(title)))
            connection.commit()


class ProductionInventoryOperations:
    def __init__(self,profile:ProductionProfile,service:FilesystemInventoryService|None=None)->None:self.profile=profile;self.service=service or FilesystemInventoryService()

    def scan(self,*,confirmed:bool,roots=LIVE_ROOTS,token=None,allow_test_roots=False)->dict:
        if not confirmed:raise PermissionError("The first production Jellyfin scan requires explicit confirmation.")
        roots=tuple(roots)
        if not allow_test_roots and tuple((root.label,root.path,root.library_kind) for root in roots)!=tuple((root.label,root.path,root.library_kind) for root in LIVE_ROOTS):raise PermissionError("Production scanning is restricted to the configured read-only roots.")
        started=datetime.now(timezone.utc);snapshot=self.service.scan(roots,token=token);completed=datetime.now(timezone.utc)
        complete=not snapshot.canceled and all(root.status in {RootScanStatus.COMPLETE,RootScanStatus.EMPTY} for root in snapshot.roots)
        snapshot_id=f"inventory-{uuid.uuid4().hex}"
        if complete:self._persist(snapshot_id,snapshot,started,completed)
        return {"snapshot_id":snapshot_id if complete else self.latest_complete_snapshot_id(),"status":"COMPLETE" if complete else "PARTIAL","complete":complete,"canceled":snapshot.canceled,"roots":[{"label":root.root.label,"status":root.status.value,"items":len(root.items),"diagnostics":len(root.diagnostics)} for root in snapshot.roots],"statistics":asdict(snapshot.statistics),"prior_complete_retained":not complete and bool(self.latest_complete_snapshot_id()),"snapshot":snapshot}

    def latest_complete_snapshot_id(self)->str:
        with closing(sqlite3.connect(f"file:{self.profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:
            row=connection.execute("SELECT snapshot_id FROM inventory_snapshots WHERE complete=1 ORDER BY completed_at DESC LIMIT 1").fetchone();return row[0] if row else ""

    def _persist(self,snapshot_id:str,snapshot:ServerInventorySnapshot,started:datetime,completed:datetime)->None:
        roots=[{"label":root.root.label,"library_kind":root.root.library_kind.value,"status":root.status.value} for root in snapshot.roots]
        diagnostics=[_json_value(item) for root in snapshot.roots for item in root.diagnostics]
        inventory=[_json_value(item) for item in snapshot.items]
        with closing(sqlite3.connect(self.profile.database_path)) as connection:connection.execute("INSERT INTO inventory_snapshots VALUES(?,?,?,?,?,?,?,?,1)",(snapshot_id,started.isoformat(),completed.isoformat(),"COMPLETE",json.dumps(roots),json.dumps(asdict(snapshot.statistics)),json.dumps(diagnostics),json.dumps(inventory)));connection.commit()


def _json_value(value):
    if is_dataclass(value):return {key:_json_value(item) for key,item in asdict(value).items()}
    if isinstance(value,Enum):return value.value
    if isinstance(value,(datetime,date)):return value.isoformat()
    if isinstance(value,(tuple,list)):return [_json_value(item) for item in value]
    if isinstance(value,dict):return {str(key):_json_value(item) for key,item in value.items()}
    return value
