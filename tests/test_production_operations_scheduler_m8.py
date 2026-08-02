from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from anime_tracker.domain.enums import LibraryKind
from anime_tracker.production.locks import FileOperationLock
from anime_tracker.production.operations import ProductionAniListOperations,ProductionInventoryOperations
from anime_tracker.production.scheduled import ScheduledCheckRunner,ScheduledRunStatus
from anime_tracker.production.task_scheduler import VALIDATION_TASK_NAME,build_install_args,install_validation_task
from anime_tracker.services.anilist.models import AniListRefreshBatch,BatchState
from anime_tracker.services.server_inventory.models import LibraryRoot
from production_helpers import production_profile


class FakeAniListService:
    def refresh_batch(self,ids,**kwargs):
        requested=tuple(ids);return AniListRefreshBatch("batch",requested,__import__("datetime").datetime.now(__import__("datetime").timezone.utc),__import__("datetime").datetime.now(__import__("datetime").timezone.utc),len(requested),len(requested),0,len(requested),0,0,0,BatchState.SUCCESS,(),())


class FakeScheduledAniList:
    def __init__(self,result):self.result=result
    def active_ids(self):return tuple(range(69))
    def refresh(self,**kwargs):return self.result


class FakeInventory:
    def __init__(self,status="COMPLETE"):self.status=status
    def scan(self,**kwargs):return {"status":self.status}


class FakeBackup:
    def create(self,reason):return Path("backup")


def test_initial_anilist_preview_deduplicates_and_excludes_archived(tmp_path):
    profile=production_profile(tmp_path);operation=ProductionAniListOperations(profile,FakeAniListService());preview=operation.preview([3,2,3,1])
    assert preview["requested_ids"]==(3,2,1) and preview["notifications_suppressed"]


def test_initial_baseline_refresh_generates_no_notification_flood(tmp_path):
    profile=production_profile(tmp_path);operation=ProductionAniListOperations(profile,FakeAniListService());result=operation.refresh([1,1,2],baseline=True)
    assert result["requested"]==2 and result["notifications_created"]==0 and result["failed"]==0


def test_read_only_inventory_requires_confirmation_and_preserves_season_scope(tmp_path):
    profile=production_profile(tmp_path);root=tmp_path/"TV";show=root/"Example Anime";(show/"Season 01").mkdir(parents=True);(show/"Season 02").mkdir();(show/"Season 01"/"Example S01E01.mkv").write_bytes(b"");(show/"Season 02"/"Example S02E01.mkv").write_bytes(b"")
    before={path:path.stat().st_mtime_ns for path in root.rglob("*")};operation=ProductionInventoryOperations(profile)
    with pytest.raises(PermissionError):operation.scan(confirmed=False,roots=(LibraryRoot("Test TV",str(root),LibraryKind.TV),),allow_test_roots=True)
    result=operation.scan(confirmed=True,roots=(LibraryRoot("Test TV",str(root),LibraryKind.TV),),allow_test_roots=True);item=result["snapshot"].items[0]
    assert result["complete"] and {season.season_number for season in item.seasons}=={1,2}
    assert item.seasons[0].present_episode_numbers=={1} and item.seasons[1].present_episode_numbers=={1}
    assert before=={path:path.stat().st_mtime_ns for path in root.rglob("*")}


def test_partial_inventory_retains_previous_complete_snapshot(tmp_path):
    profile=production_profile(tmp_path);root=tmp_path/"TV";(root/"Show").mkdir(parents=True);(root/"Show"/"S01E01.mkv").write_bytes(b"");operation=ProductionInventoryOperations(profile);library=(LibraryRoot("Test TV",str(root),LibraryKind.TV),)
    complete=operation.scan(confirmed=True,roots=library,allow_test_roots=True);missing=(LibraryRoot("Test TV",str(tmp_path/"missing"),LibraryKind.TV),);partial=operation.scan(confirmed=True,roots=missing,allow_test_roots=True)
    assert complete["complete"] and not partial["complete"] and partial["prior_complete_retained"] and partial["snapshot_id"]==complete["snapshot_id"]


def test_scheduled_success_partial_failure_and_offline_states(tmp_path):
    profile=production_profile(tmp_path);bootstrap=profile.load_bootstrap();bootstrap.update({"anilist_refresh_enabled":True,"jellyfin_scan_enabled":True});profile.save_bootstrap(bootstrap)
    success=ScheduledCheckRunner(profile,anilist=FakeScheduledAniList({"succeeded":69,"failed":0,"cache_hits":69,"state":"SUCCESS"}),inventory=FakeInventory(),backup=FakeBackup()).run();assert success.status==ScheduledRunStatus.SUCCESS
    partial=ScheduledCheckRunner(profile,anilist=FakeScheduledAniList({"succeeded":42,"failed":27,"cache_hits":0,"state":"PARTIAL_FAILURE"}),inventory=FakeInventory(),backup=FakeBackup()).run();assert partial.status==ScheduledRunStatus.PARTIAL_SUCCESS and partial.refresh_failed==27
    offline=ScheduledCheckRunner(profile,anilist=FakeScheduledAniList({"succeeded":69,"failed":0,"cache_hits":69,"state":"OFFLINE_CACHE_ONLY"}),inventory=FakeInventory(),backup=FakeBackup()).run();assert offline.status==ScheduledRunStatus.OFFLINE_CACHE_ONLY


def test_scheduled_duplicate_run_prevention(tmp_path):
    profile=production_profile(tmp_path)
    with FileOperationLock(profile.locks_dir/"scheduled-check.lock"):
        result=ScheduledCheckRunner(profile,anilist=FakeScheduledAniList({}),inventory=FakeInventory(),backup=FakeBackup()).run()
    assert result.status==ScheduledRunStatus.ALREADY_RUNNING


def test_scheduled_before_migration_returns_failed_without_creating_database(tmp_path):
    from anime_tracker.production.profile import ProductionProfile
    profile=ProductionProfile(tmp_path/"not-migrated");result=ScheduledCheckRunner(profile,anilist=FakeScheduledAniList({}),inventory=FakeInventory(),backup=FakeBackup()).run()
    assert result.status==ScheduledRunStatus.FAILED and not profile.database_path.exists()


def test_scheduler_script_is_validation_only_limited_and_keeps_legacy(tmp_path):
    source=(Path(__file__).parents[1]/"Create-ModernScheduledTask.ps1").read_text(encoding="utf-8")
    assert 'Anime Tracker Modern - Validation' in source and '-RunLevel Limited' in source and 'MultipleInstances IgnoreNew' in source
    assert 'Disable-ScheduledTask -TaskName $TaskName' in source
    assert 'Anime Tracker Weekly Check' not in source and 'Unregister-ScheduledTask' not in source


def test_task_install_requests_elevation_and_passes_safe_schedule_arguments(tmp_path):
    args=build_install_args(tmp_path,{"scheduled_checks_enabled":True,"schedule_frequency":"Weekly","schedule_day":"Sunday","schedule_time":"10:00","run_when_missed":True});command=args[-1]
    assert "-Verb RunAs" in command and "-Enabled" in command and "-StartWhenAvailable" in command
    assert "webhook" not in command.casefold() and "secret" not in command.casefold()


def test_task_install_reports_uac_cancel_failure_and_verified_success(tmp_path):
    class Result:
        def __init__(self,code=0,out="",err=""):self.returncode=code;self.stdout=out;self.stderr=err
    canceled=install_validation_task(tmp_path,{},run=lambda *a,**k:Result(1223));assert canceled["canceled"]
    failed=install_validation_task(tmp_path,{},run=lambda *a,**k:Result(1,err="Access denied"));assert not failed["installed"] and "Access denied" in failed["message"]
    calls=[]
    def run(*args,**kwargs):
        calls.append(args);return Result() if len(calls)==1 else Result(out=json.dumps({"TaskName":VALIDATION_TASK_NAME,"Enabled":True,"NextRunTime":"tomorrow","LastResult":0}))
    success=install_validation_task(tmp_path,{},run=run);assert success["installed"] and success["task"]["TaskName"]==VALIDATION_TASK_NAME


def test_production_package_has_no_media_writes_or_external_tools():
    root=Path(__file__).parents[1]/"src"/"anime_tracker"/"production";source="\n".join(path.read_text(encoding="utf-8").casefold() for path in root.rglob("*.py"))
    for forbidden in ("remove-item","move-item","mkvtoolnix","ffmpeg","handbrake","sonarr","radarr","storage checker","trigger library scan"):
        assert forbidden not in source
    assert "open(\"wb\")" not in source and "open('wb')" not in source
