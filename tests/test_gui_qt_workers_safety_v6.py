from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QThreadPool

from anime_tracker.gui_qt.workers import BackgroundWorker
from anime_tracker.gui_qt.covers import CoverImageCache


ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/"data"/"anime_tracker.db"
LIVE_HASH="69763FC9EC883096041C6EDEDD9399B4697EBC650A48D07BA87879C787B3782E"


def operation(steps=5,*,cancel_event,progress):
    completed=[]
    for index in range(steps):
        if cancel_event.is_set():break
        completed.append(index); progress(index+1,steps,f"step {index+1}"); time.sleep(.002)
    return completed


def test_worker_progress_result_and_non_ui_thread(qtbot):
    worker=BackgroundWorker(operation,4); progress=[]; results=[]; thread_ids=[]
    worker.signals.progress.connect(lambda value:progress.append(value.current)); worker.signals.result.connect(results.append); worker.signals.started.connect(lambda _:thread_ids.append(threading.get_ident()))
    with qtbot.waitSignal(worker.signals.finished,timeout=2000):QThreadPool.globalInstance().start(worker)
    assert progress==[1,2,3,4] and results==[[0,1,2,3]]


def test_worker_cancellation(qtbot):
    worker=BackgroundWorker(operation,100); canceled=[]; worker.signals.canceled.connect(canceled.append)
    worker.signals.progress.connect(lambda value:worker.cancel() if value.current==2 else None)
    with qtbot.waitSignal(worker.signals.finished,timeout=2000):QThreadPool.globalInstance().start(worker)
    assert canceled==[worker.worker_id]


def test_worker_exception_is_friendly(qtbot):
    def fail(*,cancel_event,progress):raise RuntimeError("simulated failure")
    worker=BackgroundWorker(fail); errors=[]; worker.signals.error.connect(lambda kind,detail:errors.append((kind,detail)))
    with qtbot.waitSignal(worker.signals.finished,timeout=2000):QThreadPool.globalInstance().start(worker)
    assert errors and errors[0][0]=="RuntimeError" and "Traceback" not in errors[0][1]


def test_partial_result_signal_is_available():
    worker=BackgroundWorker(operation); assert hasattr(worker.signals,"partial")


def test_worker_safe_shutdown(qtbot):
    pool=QThreadPool(); worker=BackgroundWorker(operation,100); pool.start(worker); worker.cancel(); assert pool.waitForDone(2000)


def test_gui_package_has_no_media_write_scheduler_or_credential_reads():
    source="\n".join(path.read_text(encoding="utf-8").casefold() for path in (ROOT/"src"/"anime_tracker"/"gui_qt").rglob("*.py"))
    for forbidden in ("notification_config.json","register-scheduledtask","schtasks","storage checker","remove-item","move-item","requests.post(","i:\\jellyfin_media"):
        assert forbidden not in source


def test_live_database_hash_unchanged():
    assert hashlib.sha256(LIVE.read_bytes()).hexdigest().upper()==LIVE_HASH


def test_modern_launcher_is_separate_and_legacy_launchers_remain():
    assert (ROOT/"Run-AnimeTracker-Modern.ps1").exists()
    assert (ROOT/"Run-AnimeTracker.ps1").exists()
    assert (ROOT/"Run-AnimeTracker.bat").exists()


def test_no_modern_profile_runtime_files_are_tracked():
    ignore=(ROOT/".gitignore").read_text(encoding="utf-8")
    assert "modern_profile_test/" in ignore


def test_cover_cache_placeholder_and_valid_cached_image_survives(qtbot,tmp_path):
    cache=CoverImageCache(tmp_path); placeholder=cache.request(""); assert not placeholder.isNull()
    cache.memory["https://example.invalid/cover.jpg"]=placeholder
    assert cache.request("https://example.invalid/cover.jpg").cacheKey()==placeholder.cacheKey()
