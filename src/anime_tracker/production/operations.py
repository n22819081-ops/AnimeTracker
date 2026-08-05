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
from ..services.anilist.cancellation import Cancellation
from ..services.anilist.client import AniListGraphQLClient
from ..services.anilist.service import AniListService
from ..services.server_inventory.models import LibraryRoot, RootScanStatus, ServerInventorySnapshot
from ..services.server_inventory.service import FilesystemInventoryService
from .profile import ProductionProfile


def configured_roots(profile:ProductionProfile)->tuple[LibraryRoot,...]:
    settings=profile.load_settings();values=(settings.get("tv_path","") or settings.get("test_tv_path",""),settings.get("movie_path","") or settings.get("test_movie_path",""))
    if not all(values) and profile.database_path.is_file():
        with closing(sqlite3.connect(f"file:{profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:
            stored=dict(connection.execute("SELECT key,value FROM application_settings WHERE key IN ('tv_path','movie_path')"))
        values=(values[0] or stored.get("tv_path",""),values[1] or stored.get("movie_path",""))
    return tuple(root for root in (LibraryRoot("TV Library",values[0],LibraryKind.TV) if values[0] else None,LibraryRoot("Movies Library",values[1],LibraryKind.MOVIE) if values[1] else None) if root)


class ProductionAniListOperations:
    def __init__(self,profile:ProductionProfile,service:AniListService|None=None)->None:
        self.profile=profile;self.service=service or AniListService(AniListCache(profile.database_path),AniListGraphQLClient())

    def active_ids(self)->tuple[int,...]:
        with closing(sqlite3.connect(f"file:{self.profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:return tuple(row[0] for row in connection.execute("SELECT anilist_id FROM tracked_media WHERE archived_at IS NULL ORDER BY anilist_id"))

    def preview(self,ids=None)->dict:
        requested=tuple(dict.fromkeys(ids or self.active_ids()));return {"requested_ids":requested,"count":len(requested),"deduplicated":True,"archived_excluded":True,"notifications_suppressed":True}

    def refresh(self,ids=None,*,force=False,offline=False,token:Cancellation|None=None,baseline=True)->dict:
        requested=tuple(dict.fromkeys(ids or self.active_ids()))
        before=self._metadata_fingerprints(requested)
        if offline:
            results=tuple(self.service.get_media(item,offline=True,token=token) for item in requested)
            succeeded=sum(item.success for item in results);failed=len(results)-succeeded;cache_hits=sum(item.cache_hit for item in results);state="OFFLINE_CACHE_ONLY" if succeeded else "FAILED"
        else:
            batch=self.service.refresh_batch(requested,force_refresh=force,token=token,include_archived=False)
            results=batch.results;succeeded=batch.succeeded;failed=batch.failed;cache_hits=batch.cache_hits;state=batch.state.value
        for result in results:
            if result.success and result.updated_data:self._sync_media(result.updated_data)
        after=self._metadata_fingerprints(requested)
        changed=sum(before.get(item)!=after.get(item) for item in requested)
        if baseline:
            bootstrap=self.profile.load_bootstrap();bootstrap["initial_anilist_baseline_state"]="ACCEPTED" if failed==0 else "PARTIAL";bootstrap["initial_anilist_baseline_at"]=datetime.now(timezone.utc).isoformat();self.profile.save_bootstrap(bootstrap)
        return {"state":state,"requested":len(requested),"checked":len(requested),"succeeded":succeeded,"failed":failed,"cache_hits":cache_hits,"network_requests":sum(item.network_request_count for item in results),"metadata_changes":changed,"notifications_created":0,"failures":[{"anilist_id":item.anilist_id,"error_type":item.error_type} for item in results if not item.success]}

    def _metadata_fingerprints(self,ids)->dict[int,tuple]:
        if not ids:return {}
        placeholders=",".join("?" for _ in ids)
        with closing(sqlite3.connect(f"file:{self.profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:
            rows=connection.execute(f"SELECT anilist_id,media_format,season_name,season_year,episode_count,anilist_status,start_date,end_date,cover_image_url,page_url FROM anilist_media WHERE anilist_id IN ({placeholders})",tuple(ids)).fetchall()
        return {int(row[0]):tuple(row[1:]) for row in rows}

    def _sync_media(self,media)->None:
        now=datetime.now(timezone.utc).isoformat();cover=media.cover_images.extra_large or media.cover_images.large or media.cover_images.medium
        with closing(sqlite3.connect(self.profile.database_path)) as connection:
            connection.execute("UPDATE anilist_media SET media_format=?,season_name=?,season_year=?,episode_count=?,anilist_status=?,start_date=?,end_date=?,cover_image_url=?,page_url=?,source_updated_at=? WHERE anilist_id=?",(media.media_format.value,media.season,media.season_year,media.episode_count,media.status.value,media.start_date.isoformat() if media.start_date else "",media.end_date.isoformat() if media.end_date else "",cover,media.site_url,now,media.anilist_id))
            for kind,title in (("english",media.title.english),("romaji",media.title.romaji),("native",media.title.native),*(("synonym",item) for item in media.title.synonyms)):
                if title:connection.execute("INSERT OR REPLACE INTO media_titles(anilist_id,title_type,title,normalized_title) VALUES(?,?,?,?)",(media.anilist_id,kind,title,normalize_title(title)))
            connection.commit()


class ProductionInventoryOperations:
    def __init__(self,profile:ProductionProfile,service:FilesystemInventoryService|None=None)->None:self.profile=profile;self.service=service or FilesystemInventoryService()

    def scan(self,*,confirmed:bool,roots=None,token=None,allow_test_roots=False)->dict:
        if not confirmed:raise PermissionError("The first production Jellyfin scan requires explicit confirmation.")
        configured=configured_roots(self.profile);roots=tuple(configured if roots is None else roots)
        if not roots:raise ValueError("No Jellyfin roots are configured.")
        if not allow_test_roots and tuple((root.label,root.path,root.library_kind) for root in roots)!=tuple((root.label,root.path,root.library_kind) for root in configured):raise PermissionError("Production scanning is restricted to the configured read-only roots.")
        started=datetime.now(timezone.utc);snapshot=self.service.scan(roots,token=token);completed=datetime.now(timezone.utc)
        complete=not snapshot.canceled and all(root.status in {RootScanStatus.COMPLETE,RootScanStatus.EMPTY} for root in snapshot.roots)
        snapshot_id=f"inventory-{uuid.uuid4().hex}"
        integration={"titles_processed":0,"candidate_suggestions":0,"titles_with_suggestions":0,"mappings_revalidated":0,"coverage_updated":0,"review_cases":0,"integration_failures":[]}
        if complete:
            self._persist(snapshot_id,snapshot,started,completed)
            integration=self._integrate(snapshot)
        return {"snapshot_id":snapshot_id if complete else self.latest_complete_snapshot_id(),"status":"COMPLETE" if complete else "PARTIAL","complete":complete,"canceled":snapshot.canceled,"started_at":started.isoformat(),"completed_at":completed.isoformat(),"item_count":len(snapshot.items),"roots":[{"label":root.root.label,"path":root.root.path,"status":root.status.value,"items":len(root.items),"diagnostics":len(root.diagnostics)} for root in snapshot.roots],"statistics":asdict(snapshot.statistics),"prior_complete_retained":not complete and bool(self.latest_complete_snapshot_id()),"snapshot":snapshot,**integration}

    def latest_complete_snapshot_id(self)->str:
        with closing(sqlite3.connect(f"file:{self.profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:
            row=connection.execute("SELECT snapshot_id FROM inventory_snapshots WHERE complete=1 ORDER BY completed_at DESC LIMIT 1").fetchone();return row[0] if row else ""

    def _persist(self,snapshot_id:str,snapshot:ServerInventorySnapshot,started:datetime,completed:datetime)->None:
        roots=[{"label":root.root.label,"library_kind":root.root.library_kind.value,"status":root.status.value} for root in snapshot.roots]
        diagnostics=[_json_value(item) for root in snapshot.roots for item in root.diagnostics]
        inventory=[_json_value(item) for item in snapshot.items]
        with closing(sqlite3.connect(self.profile.database_path)) as connection:connection.execute("INSERT INTO inventory_snapshots VALUES(?,?,?,?,?,?,?,?,1)",(snapshot_id,started.isoformat(),completed.isoformat(),"COMPLETE",json.dumps(roots),json.dumps(asdict(snapshot.statistics)),json.dumps(diagnostics),json.dumps(inventory)));connection.commit()

    def _integrate(self,snapshot:ServerInventorySnapshot)->dict:
        from ..services.matching.models import MatchConfidence
        from ..services.matching.repository import MatchingRepository
        from ..services.matching.service import MatchingService
        repository=MatchingRepository(self.profile.database_path);matching=MatchingService(repository)
        cache=AniListCache(self.profile.database_path);now=datetime.now(timezone.utc)
        with closing(sqlite3.connect(f"file:{self.profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:
            ids=tuple(row[0] for row in connection.execute("SELECT anilist_id FROM tracked_media WHERE archived_at IS NULL ORDER BY anilist_id"))
        suggestions=titles_with_suggestions=mappings_revalidated=coverage_updated=0;failures=[];prepared=[];media_values=[];generated_by_id={}
        viable={MatchConfidence.VERY_STRONG,MatchConfidence.STRONG,MatchConfidence.POSSIBLE}
        for anilist_id in ids:
            try:
                media=cache.get_media(anilist_id,now).media
                if media is None:
                    failures.append({"anilist_id":anilist_id,"error":"CACHE_MISSING"});continue
                generated,reviews=matching.prepare_candidates(media,snapshot,relations=media.relations,profile_id="default")
                existing_types={item.review_type for item in repository.list_reviews("default",anilist_id=anilist_id)}
                reviews=tuple(review for review in reviews if review.review_type not in existing_types)
                prepared.append((generated.session,generated.candidates,reviews));media_values.append(media)
                generated_by_id[anilist_id]=generated
                count=sum(candidate.confidence in viable for candidate in generated.candidates)
                suggestions+=count;titles_with_suggestions+=int(count>0)
            except Exception as exc:
                failures.append({"anilist_id":anilist_id,"error":type(exc).__name__})
        repository.save_generation_batch(prepared)
        for media in media_values:
            try:
                viable_ids=tuple(candidate.candidate_id for candidate in generated_by_id[media.anilist_id].candidates if candidate.confidence in viable)
                repository.reconcile_candidate_reviews("default",media.anilist_id,viable_ids,now)
                evaluations=matching.check_confirmed_mappings(media,snapshot,aired_episode_count=_aired_episode_count(media),profile_id="default")
                mappings_revalidated+=len(evaluations);coverage_updated+=sum(evaluation.coverage is not None for evaluation in evaluations)
                self._sync_tracking_state(media.anilist_id,evaluations,now)
                if not evaluations:self._sync_unmapped_review_state(media.anilist_id,now)
            except Exception as exc:
                failures.append({"anilist_id":media.anilist_id,"error":type(exc).__name__})
        with closing(sqlite3.connect(f"file:{self.profile.database_path.as_posix()}?mode=ro",uri=True)) as connection:
            reviews=connection.execute("SELECT count(*) FROM review_cases WHERE state IN ('OPEN','ACKNOWLEDGED')").fetchone()[0]
        return {"titles_processed":len(media_values),"candidate_suggestions":suggestions,"titles_with_suggestions":titles_with_suggestions,"mappings_revalidated":mappings_revalidated,"coverage_updated":coverage_updated,"review_cases":reviews,"integration_failures":failures}

    def _sync_tracking_state(self,anilist_id,evaluations,when:datetime)->None:
        if not evaluations:return
        presence=evaluations[0].server_presence.value
        coverage=evaluations[0].coverage
        legacy_presence={"COMPLETE":"ON_SERVER","PARTIAL":"PARTIAL","UNKNOWN_COVERAGE":"UNKNOWN_COVERAGE","PATH_MISSING":"NEEDS_REVIEW","NOT_FOUND":"NOT_ON_SERVER"}.get(presence,"UNKNOWN_COVERAGE")
        coverage_state="UNKNOWN"
        if coverage is not None:
            if presence=="COMPLETE":coverage_state="COMPLETE"
            elif presence=="PARTIAL":coverage_state="PARTIAL"
            elif presence=="NOT_FOUND":coverage_state="NONE"
        with closing(sqlite3.connect(self.profile.database_path)) as connection:
            tracked=connection.execute("SELECT id FROM tracked_media WHERE anilist_id=? AND archived_at IS NULL",(anilist_id,)).fetchone()
            if tracked is None:return
            open_reviews=connection.execute("SELECT count(*) FROM review_cases WHERE profile_id='default' AND anilist_id=? AND state IN ('OPEN','ACKNOWLEDGED')",(anilist_id,)).fetchone()[0]
            tracker="On Server" if presence=="COMPLETE" else ("Needs Review" if presence=="PATH_MISSING" or open_reviews else None)
            if tracker:
                connection.execute("UPDATE tracking_state SET tracker_status=?,server_presence=?,episode_coverage=?,review_status=?,review_reason=?,last_checked=? WHERE tracked_media_id=?",(tracker,legacy_presence,coverage_state,"OPEN" if open_reviews else "NONE","Confirmed mapping requires review." if open_reviews else "",when.isoformat(),tracked[0]))
            else:
                connection.execute("UPDATE tracking_state SET server_presence=?,episode_coverage=?,last_checked=? WHERE tracked_media_id=?",(legacy_presence,coverage_state,when.isoformat(),tracked[0]))
            connection.commit()

    def _sync_unmapped_review_state(self,anilist_id:int,when:datetime)->None:
        with closing(sqlite3.connect(self.profile.database_path)) as connection:
            row=connection.execute("SELECT tm.id,am.anilist_status,am.media_format,ts.tracker_status FROM tracked_media tm JOIN anilist_media am ON am.anilist_id=tm.anilist_id JOIN tracking_state ts ON ts.tracked_media_id=tm.id WHERE tm.anilist_id=? AND tm.archived_at IS NULL",(anilist_id,)).fetchone()
            if row is None:return
            open_reviews=connection.execute("SELECT review_type FROM review_cases WHERE profile_id='default' AND anilist_id=? AND state IN ('OPEN','ACKNOWLEDGED') ORDER BY created_at",(anilist_id,)).fetchall()
            if open_reviews:
                reason="; ".join(value[0].replace("_"," ").title() for value in open_reviews)
                connection.execute("UPDATE tracking_state SET tracker_status='Needs Review',server_presence='NEEDS_REVIEW',review_status='OPEN',review_reason=?,last_checked=? WHERE tracked_media_id=?",(reason,when.isoformat(),row[0]))
            elif row[3]=="Needs Review":
                tracker=_tracker_status(row[1],row[2],row[3])
                connection.execute("UPDATE tracking_state SET tracker_status=?,server_presence='NOT_ON_SERVER',episode_coverage='NONE',review_status='NONE',review_reason='',last_checked=? WHERE tracked_media_id=?",(tracker,when.isoformat(),row[0]))
            connection.commit()


def _aired_episode_count(media)->int|None:
    if media.status.value=="FINISHED":return media.episode_count
    if media.airing_schedule.previous_episode:return media.airing_schedule.previous_episode.episode_number
    if media.next_airing_episode:return max(0,media.next_airing_episode.episode_number-1)
    return None


def _tracker_status(anilist_status:str,media_format:str,previous:str)->str:
    if media_format=="MOVIE" and previous in {"Movie Theatrical Only","Movie Digitally Available"}:return previous
    if anilist_status=="RELEASING":return "Currently Airing"
    if anilist_status in {"NOT_YET_RELEASED","HIATUS"}:return "Upcoming"
    if anilist_status in {"FINISHED","CANCELLED"}:return "Finished / Ready to Add"
    return "Upcoming"


def _json_value(value):
    if is_dataclass(value):return {key:_json_value(item) for key,item in asdict(value).items()}
    if isinstance(value,Enum):return value.value
    if isinstance(value,(datetime,date)):return value.isoformat()
    if isinstance(value,(tuple,list)):return [_json_value(item) for item in value]
    if isinstance(value,dict):return {str(key):_json_value(item) for key,item in value.items()}
    return value
