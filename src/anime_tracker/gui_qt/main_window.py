from __future__ import annotations

import time
from collections import OrderedDict

from PySide6.QtCore import QByteArray, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QStackedWidget, QStyle, QToolButton,
    QVBoxLayout, QWidget,
)

from .data import ModernRepository
from .dialogs import AddAnimeDialog, AnimeDetailDialog, LegacyImportPreviewDialog, MatchingReviewDialog
from .pages import (
    AnimeListPage, CoveragePage, DashboardPage, FranchisePage, HistoryPage, MoviesPage,
    NotificationsPage, ReviewPage, SettingsPage,
)
from .profile import ModernProfile
from .theme import apply_theme
from .workers import BackgroundWorker, WorkerProgress


PAGE_LABELS = (
    "Dashboard","Upcoming","Currently Airing","Finished / Ready to Add","Movies","On Server",
    "Needs Review","Franchises","Jellyfin Coverage","Notifications","History","Settings",
)


class MainWindow(QMainWindow):
    page_changed = Signal(str)

    def __init__(self, profile: ModernProfile, repository: ModernRepository, parent=None, *, production=False) -> None:
        super().__init__(parent); self.profile=profile; self.repository=repository; self.production=production; self.settings=profile.load_settings(); self.settings=({**profile.load_bootstrap(),**self.settings,**_production_root_settings()} if production else self.settings); self.thread_pool=QThreadPool(self); self.workers={}
        self.setWindowTitle("Anime Tracker · Production Profile" if production else "Anime Tracker · Development / Migration Test Profile"); self.setMinimumSize(1200,760); self.resize(1380,860)
        self._build(); self._restore(); apply_theme(QApplication.instance(),self.settings.get("theme","Dark"))

    def _build(self):
        central=QWidget(); outer=QVBoxLayout(central); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        if self.production:
            state=self.profile.load_bootstrap().get("cutover_state","PENDING_APPROVAL");banner_text=f"PRODUCTION PROFILE · Cutover {state.replace('_',' ').title()} · Media access read-only"
        else:banner_text="DEVELOPMENT / MIGRATION TEST PROFILE · Production cutover and delivery disabled"
        banner=QLabel(banner_text); banner.setObjectName("profileBanner"); banner.setAlignment(Qt.AlignCenter); outer.addWidget(banner)
        body=QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0); outer.addLayout(body,1); self.setCentralWidget(central)
        sidebar=QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(225); side=QVBoxLayout(sidebar); brand=QLabel("Anime Tracker"); brand.setStyleSheet("font-size: 16pt; font-weight: 700; padding: 10px;"); side.addWidget(brand)
        self.navigation=QListWidget(); self.navigation.setAccessibleName("Main navigation")
        for label in PAGE_LABELS:self.navigation.addItem(QListWidgetItem(label))
        self.navigation.currentTextChanged.connect(self.show_page); side.addWidget(self.navigation,1)
        safety=QLabel("Modern profile\nRead-only media access"); safety.setObjectName("muted"); safety.setAlignment(Qt.AlignCenter); side.addWidget(safety); body.addWidget(sidebar)
        content=QWidget(); content_layout=QVBoxLayout(content); content_layout.setContentsMargins(0,0,0,0); content_layout.setSpacing(0); body.addWidget(content,1)
        toolbar=QFrame(); toolbar.setObjectName("toolbar"); tools=QHBoxLayout(toolbar); tools.setContentsMargins(14,9,14,9)
        self.search=QLineEdit(); self.search.setPlaceholderText("Search titles, status, format, year, or mapping"); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self._search_current); tools.addWidget(self.search,1)
        self.refresh=QToolButton(); self.refresh.setText("Refresh"); self.refresh.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload)); self.refresh.clicked.connect(self.start_refresh); self.refresh.setToolTip("Refresh visible cached data in a background worker")
        self.scan=QToolButton(); self.scan.setText("Scan Jellyfin"); self.scan.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon)); self.scan.clicked.connect(self.start_scan); self.scan.setToolTip("Scan explicitly configured test roots read-only")
        self.add=QPushButton("Add Anime"); self.add.setObjectName("primary"); self.add.clicked.connect(self.open_add); tools.addWidget(self.refresh); tools.addWidget(self.scan); tools.addWidget(self.add); content_layout.addWidget(toolbar)
        self.stack=QStackedWidget(); content_layout.addWidget(self.stack,1)
        status=QFrame(); status.setObjectName("toolbar"); status_layout=QHBoxLayout(status); status_layout.setContentsMargins(14,6,14,6)
        self.task_status=QLabel("Ready · cached profile"); self.task_status.setObjectName("muted"); self.progress=QProgressBar(); self.progress.setFixedWidth(190); self.progress.hide(); self.last_refresh=QLabel("Last refresh: cached"); self.last_scan=QLabel("Last scan: not run"); self.notification_health=QLabel("Notifications: test mode")
        status_layout.addWidget(self.task_status,1); status_layout.addWidget(self.progress); status_layout.addWidget(self.last_refresh); status_layout.addWidget(self.last_scan); status_layout.addWidget(self.notification_health); content_layout.addWidget(status)
        self.pages=OrderedDict(); self._create_pages()
        shortcut=QAction(self); shortcut.setShortcut(QKeySequence("Ctrl+K")); shortcut.triggered.connect(self.search.setFocus); self.addAction(shortcut)

    def _create_pages(self):
        rows=lambda:self.repository.tracked_media()
        pages={
            "Dashboard":DashboardPage(self.repository),
            "Upcoming":AnimeListPage("Upcoming",self.repository,lambda r:r.tracker_status=="Upcoming"),
            "Currently Airing":AnimeListPage("Currently Airing",self.repository,lambda r:r.tracker_status=="Currently Airing","Airing schedule times display locally; cached timestamps remain UTC."),
            "Finished / Ready to Add":AnimeListPage("Finished / Ready to Add",self.repository,lambda r:r.tracker_status=="Finished / Ready to Add" and r.server_status!="COMPLETE"),
            "Movies":MoviesPage(self.repository),
            "On Server":AnimeListPage("On Server",self.repository,lambda r:r.server_status=="COMPLETE","AniList status remains visible independently from complete server coverage."),
            "Needs Review":ReviewPage(self.repository),
            "Franchises":FranchisePage(self.repository),
            "Jellyfin Coverage":CoveragePage(self.repository),
            "Notifications":NotificationsPage(self.repository),
            "History":HistoryPage(self.repository),
            "Settings":SettingsPage(self.settings,production=self.production,diagnostics=self._diagnostics()),
        }
        for name,page in pages.items():
            self.pages[name]=page; self.stack.addWidget(page)
            if isinstance(page,AnimeListPage):
                page.row_activated.connect(self.open_detail)
                widths=self.settings.get("table_columns",{}).get(name,())
                for index,width in enumerate(widths[:page.table.model.columnCount()]):page.table.view.setColumnWidth(index,int(width))
            if isinstance(page,FranchisePage):page.row_activated.connect(self.open_detail)
            if isinstance(page,ReviewPage):page.review_requested.connect(self.open_review)
            if isinstance(page,SettingsPage):
                page.theme_changed.connect(self.change_theme);page.preview_requested.connect(self.open_preview);page.reset_requested.connect(self.reset_profile)
                if self.production:page.schedule_run_requested.connect(self.run_scheduled_now);page.schedule_install_requested.connect(self.install_validation_task);page.schedule_logs_requested.connect(self.show_scheduled_log)

    def show_page(self,name):
        if name not in self.pages:return
        self.stack.setCurrentWidget(self.pages[name]); self.settings["last_page"]=name; self.page_changed.emit(name); self._search_current(self.search.text())

    def _search_current(self,text):
        page=self.stack.currentWidget()
        if hasattr(page,"set_search"):page.set_search(text)

    def _restore(self):
        geometry=self.settings.get("window_geometry")
        if geometry:
            try:self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except Exception:pass
        target=self.settings.get("last_page","Dashboard"); labels=[self.navigation.item(i).text() for i in range(self.navigation.count())]; self.navigation.setCurrentRow(labels.index(target) if target in labels else 0)

    def change_theme(self,name):
        self.settings["theme"]=name; apply_theme(QApplication.instance(),name)

    def start_refresh(self):
        if self.production:
            if QMessageBox.question(self,"Refresh AniList","Refresh all active titles from AniList? Cached data is preserved on partial failure and no baseline notifications are generated.")!=QMessageBox.Yes:return
            self._start_worker("AniList refresh all active",_production_refresh,self.profile)
        else:self._start_worker("Cache refresh",_simulated_operation,42)

    def start_scan(self):
        if self.production:
            message="Scan these roots read-only?\n\n"+"\n".join(_production_root_lines())+"\n\nNo media files or folders will be modified."
            if QMessageBox.question(self,"Confirm read-only Jellyfin scan",message)!=QMessageBox.Yes:return
            self._start_worker("Read-only production inventory scan",_production_scan,self.profile);return
        settings_page=self.pages["Settings"]
        if not settings_page.tv.text().strip() and not settings_page.movies.text().strip():
            QMessageBox.information(self,"Test paths required","Choose explicit test Jellyfin paths in Settings. Production roots are never scanned automatically."); return
        self._start_worker("Read-only test inventory scan",_simulated_operation,60)

    def _start_worker(self,label,operation,*args):
        worker=BackgroundWorker(operation,*args,worker_id=f"ui-{label.casefold().replace(' ','-')}-{time.time_ns()}")
        worker.signals.started.connect(lambda _:self._task_started(label)); worker.signals.progress.connect(self._task_progress); worker.signals.result.connect(lambda value:self._task_result(label,value)); worker.signals.error.connect(self._task_error); worker.signals.finished.connect(lambda wid:self.workers.pop(wid,None)); self.workers[worker.worker_id]=worker; self.thread_pool.start(worker)

    def _task_started(self,label):self.task_status.setText(label); self.progress.setRange(0,100); self.progress.setValue(0); self.progress.show()
    def _task_progress(self,value:WorkerProgress):self.progress.setMaximum(max(value.total,1)); self.progress.setValue(value.current); self.task_status.setText(value.message or value.worker_id)
    def _task_result(self,label,result=None):
        self.progress.hide(); self.task_status.setText(f"{label} completed"+("" if self.production else " in test mode"))
        if label=="Validation task installation" and isinstance(result,dict) and not result.get("installed"):
            message=result.get("message","Task registration failed.");self.task_status.setText(message);QMessageBox.warning(self,"Validation task not installed",message);return
        if hasattr(result,"status") and result.status not in {"SUCCESS","OFFLINE_CACHE_ONLY"}:
            self.task_status.setText(f"{label}: {result.status}")
        if isinstance(result,dict) and result.get("failed"):
            self.task_status.setText(f"{label}: {result.get('succeeded',0)} succeeded, {result['failed']} failed")
        if "refresh" in label.casefold():self.last_refresh.setText("Last refresh: just now")
        else:self.last_scan.setText("Last scan: just now")
        for page in self.pages.values():
            if hasattr(page,"refresh"):page.refresh()
    def _task_error(self,kind,detail):self.progress.hide(); self.task_status.setText(f"Task failed: {kind}"); QMessageBox.warning(self,"Background task failed",f"The operation could not finish.\n\n{detail}")

    def open_add(self):
        provider=_production_search_provider(self.profile) if self.production else None
        AddAnimeDialog(search_provider=provider,parent=self,background_search=self.production).exec()
    def open_detail(self,row):AnimeDetailDialog(row,self).exec()
    def open_review(self,review):MatchingReviewDialog(review,self).exec()
    def open_preview(self):LegacyImportPreviewDialog(self.repository,self).exec()
    def run_scheduled_now(self):self._start_worker("Production scheduled check",_production_scheduled_check,self.profile)
    def install_validation_task(self):
        settings_page=self.pages["Settings"];settings={"scheduled_checks_enabled":settings_page.schedule_enabled.isChecked(),"schedule_frequency":settings_page.schedule_frequency.currentText(),"schedule_day":settings_page.schedule_day.currentText(),"schedule_time":settings_page.schedule_time.text(),"run_when_missed":settings_page.run_missed.isChecked()};self._start_worker("Validation task installation",_production_install_task,self.profile,settings)
    def show_scheduled_log(self):
        path=self.profile.logs_dir/"scheduled-check-latest.json"
        QMessageBox.information(self,"Last scheduled run",path.read_text(encoding="utf-8") if path.is_file() else "No scheduled-run result is available.")
    def reset_profile(self):
        if self.production:
            QMessageBox.warning(self,"Production reset blocked","Production reset requires a verified backup and an explicit command-line confirmation. It cannot be performed from this button.");return
        if QMessageBox.question(self,"Reset test profile","Replace the disposable modern profile with a fresh migration-test copy?")==QMessageBox.Yes:
            self.profile.reset(); QMessageBox.information(self,"Test profile reset","The disposable test profile was reset. Restart the modern GUI to reload all repositories.")

    def closeEvent(self,event:QCloseEvent):
        for worker in tuple(self.workers.values()):worker.cancel()
        self.thread_pool.waitForDone(1500); self.settings["window_geometry"]=bytes(self.saveGeometry().toBase64()).decode("ascii")
        settings_page=self.pages["Settings"]; self.settings["test_tv_path"]=settings_page.tv.text(); self.settings["test_movie_path"]=settings_page.movies.text()
        self.settings.update({"scheduled_checks_enabled":settings_page.schedule_enabled.isChecked(),"schedule_frequency":settings_page.schedule_frequency.currentText(),"schedule_day":settings_page.schedule_day.currentText(),"schedule_time":settings_page.schedule_time.text(),"run_when_missed":settings_page.run_missed.isChecked(),"anilist_refresh_enabled":settings_page.schedule_anilist.isChecked(),"jellyfin_scan_enabled":settings_page.schedule_jellyfin.isChecked(),"private_notifications_enabled":settings_page.schedule_private.isChecked(),"shared_notifications_enabled":settings_page.schedule_shared.isChecked(),"weekly_summaries_enabled":settings_page.schedule_summary.isChecked()})
        widths={}
        for name,page in self.pages.items():
            if isinstance(page,AnimeListPage):widths[name]=[page.table.view.columnWidth(index) for index in range(page.table.model.columnCount())]
        self.settings["table_columns"]=widths; self.profile.save_settings(self.settings)
        if self.production:
            bootstrap=self.profile.load_bootstrap()
            for key in ("scheduled_checks_enabled","anilist_refresh_enabled","jellyfin_scan_enabled","private_notifications_enabled","shared_notifications_enabled","weekly_summaries_enabled"):bootstrap[key]=self.settings[key]
            self.profile.save_bootstrap(bootstrap)
        super().closeEvent(event)

    def _diagnostics(self):
        if not self.production:return None
        try:
            from ..production.diagnostics import DiagnosticsReporter
            return DiagnosticsReporter(self.profile).health(local_only=True)
        except Exception:return {"profile_state":"Unavailable","database_integrity":"Check failed","media_safety":"READ_ONLY"}


def _simulated_operation(steps:int,*,cancel_event,progress):
    for index in range(steps):
        if cancel_event.is_set():return {"canceled":True,"completed":index}
        time.sleep(0.002); progress(index+1,steps,f"Development task {index+1} of {steps}")
    return {"canceled":False,"completed":steps}


class _EventToken:
    def __init__(self,event):self.event=event
    @property
    def is_canceled(self):return self.event.is_set()


def _production_refresh(profile,*,cancel_event,progress):
    from ..production.operations import ProductionAniListOperations
    operation=ProductionAniListOperations(profile);preview=operation.preview();progress(0,preview["count"],f"Preparing {preview['count']} active AniList identities")
    result=operation.refresh(token=_EventToken(cancel_event),baseline=False);progress(result["succeeded"]+result["failed"],preview["count"],f"{result['succeeded']} refreshed, {result['failed']} failed");return result


def _production_scan(profile,*,cancel_event,progress):
    from ..production.operations import ProductionInventoryOperations
    progress(0,2,"Scanning TV Library read-only");result=ProductionInventoryOperations(profile).scan(confirmed=True,token=_EventToken(cancel_event));progress(2,2,f"Inventory {result['status'].casefold()}");return result


def _production_scheduled_check(profile,*,cancel_event,progress):
    from ..production.scheduled import ScheduledCheckRunner
    progress(0,1,"Running scheduled-check pipeline");result=ScheduledCheckRunner(profile).run();progress(1,1,f"Scheduled check: {result.status}");return result


def _production_install_task(profile,settings,*,cancel_event,progress):
    from ..production.task_scheduler import install_validation_task
    progress(0,1,"Requesting Windows Task Scheduler validation task");result=install_validation_task(profile.root.parent,settings);progress(1,1,"Validation task request completed");return result


def _production_search_provider(profile):
    from ..production.operations import ProductionAniListOperations
    service=ProductionAniListOperations(profile).service
    def provider(query,year,format_value,page=1):
        from ..domain.enums import MediaKind
        media_format=MediaKind(format_value) if format_value else None
        values=service.search_media(query,year=year,media_format=media_format,page=page)
        return tuple({"anilist_id":item.anilist_id,"title":item.title.english or item.title.romaji or item.title.primary,"alternate_title":" / ".join(value for value in (item.title.romaji,item.title.native) if value),"format":item.media_format.value,"year":item.season_year,"status":item.status.value,"episodes":item.episode_count,"cover_url":item.cover_images.medium,"related":tuple({"anilist_id":relation.target_anilist_id,"title":relation.target_title,"format":relation.target_format.value,"year":"","relation":relation.relation_type.value} for relation in item.relations if relation.target_anilist_id)} for item in values)
    return provider


def _production_root_settings():
    from ..production.operations import LIVE_ROOTS
    return {"test_tv_path":LIVE_ROOTS[0].path,"test_movie_path":LIVE_ROOTS[1].path}


def _production_root_lines():
    from ..production.operations import LIVE_ROOTS
    return tuple(f"{root.label}: {root.path}" for root in LIVE_ROOTS)
