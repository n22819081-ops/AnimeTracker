from __future__ import annotations

import logging
import time
from collections import OrderedDict

from PySide6.QtCore import QByteArray, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QStackedWidget, QStyle, QToolButton,
    QVBoxLayout, QWidget,
)

from .data import ModernRepository, TitleMetadata, resolve_display_title
from .dialogs import AddAnimeDialog, AnimeDetailDialog, LegacyImportPreviewDialog, MatchingReviewDialog
from .pages import (
    AnimeListPage, CoveragePage, DashboardPage, FranchisePage, HistoryPage, MoviesPage,
    NotificationsPage, ReviewPage, SettingsPage,
)
from .profile import ModernProfile
from .theme import apply_theme
from .workers import BackgroundWorker, WorkerProgress
from ..runtime import APP_VERSION


LOGGER=logging.getLogger(__name__)


PAGE_LABELS = (
    "Dashboard","Upcoming","Currently Airing","Finished / Ready to Add","Movies","On Server",
    "Needs Review","Franchises","Jellyfin Coverage","Notifications","History","Settings",
)


class MainWindow(QMainWindow):
    page_changed = Signal(str)

    def __init__(self, profile: ModernProfile, repository: ModernRepository, parent=None, *, production=False) -> None:
        super().__init__(parent); self.profile=profile; self.repository=repository; self.production=production; self.settings=profile.load_settings(); self.settings=({**profile.load_bootstrap(),**self.settings,**_production_root_settings(profile)} if production else self.settings); self.thread_pool=QThreadPool(self); self.workers={}
        self.setWindowTitle(f"Anime Tracker {APP_VERSION} · Production Profile" if production else f"Anime Tracker {APP_VERSION} · Development / Migration Test Profile"); self.setMinimumSize(1200,760); self.resize(1380,860)
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
        self.scan=QToolButton(); self.scan.setText("Scan Jellyfin Libraries — Read Only" if self.production else "Scan Test Jellyfin Roots — Read Only"); self.scan.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon)); self.scan.clicked.connect(self.start_scan); self.scan.setToolTip("Scan the configured production Jellyfin roots without modifying media" if self.production else "Scan explicitly configured test roots read-only")
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
            "Dashboard":DashboardPage(self.repository,production=self.production),
            "Upcoming":AnimeListPage("Upcoming",self.repository,lambda r:r.tracker_status=="Upcoming",filter_options={"All":lambda r:True,"This year":lambda r:r.year is not None,"No release year":lambda r:r.year is None}),
            "Currently Airing":AnimeListPage("Currently Airing",self.repository,lambda r:r.tracker_status=="Currently Airing","Airing schedule times display locally; cached timestamps remain UTC.",{
                "All":lambda r:True,"Missing aired episodes":lambda r:r.server_status=="PARTIAL","Complete so far":lambda r:r.coverage in {"CURRENT_COMPLETE","COMPLETE"},"Airing this week":lambda r:bool(r.next_airing_at),"No schedule":lambda r:not r.next_airing_at,"Refresh failed":lambda r:not r.last_updated,"On server":lambda r:r.server_status=="COMPLETE","Not on server":lambda r:r.server_status in {"NOT_ON_SERVER","NOT_FOUND"},
            }),
            "Finished / Ready to Add":AnimeListPage("Finished / Ready to Add",self.repository,lambda r:r.tracker_status=="Finished / Ready to Add" and r.server_status!="COMPLETE",filter_options={
                "All":lambda r:True,"Partial":lambda r:r.server_status=="PARTIAL","Not found":lambda r:r.server_status in {"NOT_ON_SERVER","NOT_FOUND"},"Unknown coverage":lambda r:r.coverage=="UNKNOWN","Needs mapping":lambda r:r.mapping_label=="No confirmed server mapping",
            }),
            "Movies":MoviesPage(self.repository),
            "On Server":AnimeListPage("On Server",self.repository,lambda r:r.server_status=="COMPLETE" or r.tracker_status=="On Server","AniList status remains visible independently from complete server coverage.",{
                "All":lambda r:True,"Currently airing":lambda r:r.anilist_status=="RELEASING","Finished":lambda r:r.anilist_status=="FINISHED","Movie":lambda r:r.media_format=="MOVIE","Series":lambda r:r.media_format=="TV","Unknown coverage warning":lambda r:r.coverage=="UNKNOWN",
            }),
            "Needs Review":ReviewPage(self.repository),
            "Franchises":FranchisePage(self.repository),
            "Jellyfin Coverage":CoveragePage(self.repository),
            "Notifications":NotificationsPage(self.repository,production=self.production),
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
            self._assert_active_profile()
            if QMessageBox.question(self,"Refresh AniList","Refresh all active titles from AniList? Cached data is preserved on partial failure and no baseline notifications are generated.")!=QMessageBox.Yes:return
            self._start_worker("AniList refresh all active",_production_refresh,self.profile)
        else:self._start_worker("Cache refresh",_simulated_operation,42)

    def start_scan(self):
        if self.production:
            self._assert_active_profile()
            message="Scan these roots read-only?\n\n"+"\n".join(_production_root_lines(self.profile))+"\n\nNo media files or folders will be modified."
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
        summary=_operation_summary(label,result)
        if "refresh" in label.casefold():self.last_refresh.setText(f"Last refresh: {result.get('completed_at','just now') if isinstance(result,dict) else 'just now'}")
        else:self.last_scan.setText(f"Last scan: {result.get('completed_at','just now') if isinstance(result,dict) else 'just now'}")
        self._refresh_pages();self.last_operation_summary=summary
        if self.production and summary:QMessageBox.information(self,f"{label} complete",summary)
    def _task_error(self,kind,detail):LOGGER.error("Background operation failed (%s): %s",kind,detail);self.progress.hide(); self.task_status.setText(f"Task failed: {kind}"); QMessageBox.warning(self,"Background task failed",f"The operation could not finish.\n\n{detail}")

    def open_add(self):
        provider=_production_search_provider(self.profile) if self.production else None
        AddAnimeDialog(search_provider=provider,parent=self,background_search=self.production).exec()
    def open_detail(self,row):
        dialog=AnimeDetailDialog(row,self,details=self.repository.media_details(row.anilist_id))
        dialog.review_server_match_requested.connect(lambda value:self._review_from_detail(dialog,value))
        dialog.view_franchise_requested.connect(lambda value:self._franchise_from_detail(dialog,value))
        dialog.exec()

    def _review_from_detail(self,dialog,row):
        dialog.accept();review=self.repository.review_for_anime(row.anilist_id)
        if review is None:
            QMessageBox.information(self,"No server suggestion","No current Jellyfin candidate is available for this title. Run a read-only Jellyfin scan after adding it to the server.");return
        self.open_review(review)

    def _franchise_from_detail(self,dialog,row):
        dialog.accept();self.navigation.setCurrentRow(PAGE_LABELS.index("Franchises"));self.search.setText(row.title)

    def open_review(self,review):
        dialog=MatchingReviewDialog(review,self);dialog.mark_not_on_server_requested.connect(lambda value:self._mark_review_not_on_server(value,dialog));dialog.suppress_auto_match_requested.connect(lambda value:self._suppress_review_matching(value,dialog));dialog.confirm_candidate_requested.connect(lambda value,candidate:self._confirm_review_candidate(value,candidate,dialog));dialog.reject_candidate_requested.connect(lambda value,candidate:self._reject_review_candidate(value,candidate,dialog));dialog.exec()

    def _confirm_review_candidate(self,review,candidate,dialog):
        if dialog.confirm:dialog.confirm.setEnabled(False)
        try:
            self._assert_active_profile()
            from ..production.operations import ProductionInventoryOperations
            result=ProductionInventoryOperations(self.profile).confirm_candidate(str(candidate["candidate_id"]),int(review["anilist_id"]),profile_id=str(review.get("profile_id") or "default"))
        except Exception as exc:
            LOGGER.exception("Candidate confirmation failed for AniList %s",review.get("anilist_id"));dialog.show_action_error(f"Confirmation failed: {exc}");QMessageBox.warning(dialog,"Mapping not confirmed",f"The server match could not be confirmed.\n\n{exc}")
            if dialog.confirm:dialog.confirm.setEnabled(True)
            return
        self._refresh_pages();dialog.accept();season=f" · Season {result['season_number']:02d}" if result.get("season_number") is not None else "";QMessageBox.information(self,"Server match confirmed",f"{result.get('target') or 'Jellyfin target'}{season}\n\nServer presence: {result.get('server_presence','Unknown').replace('_',' ').title()}")

    def _reject_review_candidate(self,review,candidate,dialog):
        try:
            self._assert_active_profile()
            from ..services.matching.models import MatchingRejectionScope
            from ..services.matching.repository import MatchingRepository
            from ..services.matching.service import MatchingService
            MatchingService(MatchingRepository(self.profile.database_path)).reject_candidate(str(candidate["candidate_id"]),MatchingRejectionScope.CANDIDATE,profile_id=str(review.get("profile_id") or "default"),reason="Rejected from Review Server Match.")
        except Exception as exc:
            LOGGER.exception("Candidate rejection failed for AniList %s",review.get("anilist_id"));dialog.show_action_error(f"Rejection failed: {exc}");QMessageBox.warning(dialog,"Candidate not rejected",f"The candidate could not be rejected.\n\n{exc}");return
        self._refresh_pages();dialog.accept();QMessageBox.information(self,"Candidate rejected","The rejection was saved. A later read-only scan will keep this target rejected.")

    def _mark_review_not_on_server(self,review,dialog):
        try:
            self._assert_active_profile()
            from ..services.matching.repository import MatchingRepository
            from ..services.matching.service import MatchingService
            service=MatchingService(MatchingRepository(self.profile.database_path))
            if review.get("review_id"):service.resolve_review_not_on_server(str(review["review_id"]),int(review["anilist_id"]),profile_id=str(review.get("profile_id") or "default"))
            else:service.mark_not_on_server(int(review["anilist_id"]),profile_id=str(review.get("profile_id") or "default"),reason="Manually confirmed not on the Jellyfin server.")
        except Exception as exc:
            LOGGER.exception("Mark Not on Server failed for AniList %s",review.get("anilist_id"));dialog.show_action_error(f"Mark Not on Server failed: {exc}");QMessageBox.warning(dialog,"Decision not saved",f"The decision could not be saved.\n\n{exc}");return
        self._refresh_pages();dialog.accept()

    def _suppress_review_matching(self,review,dialog):
        try:
            self._assert_active_profile()
            from ..services.matching.repository import MatchingRepository
            from ..services.matching.service import MatchingService
            MatchingService(MatchingRepository(self.profile.database_path)).suppress_auto_match(
                int(review["anilist_id"]),profile_id=str(review.get("profile_id") or "default"),reason="Suppressed from matching review.",
            )
        except Exception as exc:
            LOGGER.exception("Automatic matching suppression failed for AniList %s",review.get("anilist_id"));dialog.show_action_error(f"Suppression failed: {exc}");QMessageBox.warning(dialog,"Suppression not saved",f"Automatic matching could not be suppressed.\n\n{exc}");return
        self._refresh_pages();dialog.accept()

    def _assert_active_profile(self):
        if self.repository.database_path.resolve()!=self.profile.database_path.resolve():
            raise RuntimeError("Active profile mismatch: the GUI repository and operation profile differ.")

    def _refresh_pages(self):
        for page in self.pages.values():
            if hasattr(page,"refresh"):page.refresh()
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
        self.settings.update({"notifications_private_enabled":settings_page.private_notifications.isChecked(),"notifications_shared_enabled":settings_page.shared_notifications.isChecked(),"notifications_windows_enabled":settings_page.windows_notifications.isChecked()})
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


def _production_refresh(profile,*,cancel_event,progress):
    from ..production.operations import ProductionAniListOperations
    operation=ProductionAniListOperations(profile);preview=operation.preview();progress(0,preview["count"],f"Preparing {preview['count']} active AniList identities")
    result=operation.refresh(token=cancel_event,baseline=False);result["completed_at"]=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat();progress(result["succeeded"]+result["failed"],preview["count"],f"{result['succeeded']} refreshed, {result['failed']} failed");return result


def _production_scan(profile,*,cancel_event,progress):
    from ..production.operations import ProductionInventoryOperations
    progress(0,2,"Scanning TV Library read-only");result=ProductionInventoryOperations(profile).scan(confirmed=True,token=cancel_event);progress(2,2,f"Inventory {result['status'].casefold()}");return result


def _operation_summary(label,result)->str:
    if not isinstance(result,dict):return ""
    if "refresh" in label.casefold():
        heading="AniList refresh complete" if not result.get("failed") else "AniList refresh: Partial Success"
        return "\n".join((heading,f"- {result.get('checked',result.get('requested',0))} titles checked",f"- {result.get('succeeded',0)} succeeded",f"- {result.get('failed',0)} failed",f"- {result.get('cache_hits',0)} cache hits",f"- {result.get('network_requests',0)} network requests",f"- {result.get('metadata_changes',0)} metadata changes"))
    if "inventory scan" in label.casefold():
        stats=result.get("statistics",{})
        return "\n".join(("Jellyfin scan complete",f"{result.get('item_count',0)} library items",f"{stats.get('files_seen',0)} files",f"{stats.get('media_files_seen',0)} media files",f"{result.get('candidate_suggestions',0)} candidate suggestions",f"{result.get('mappings_revalidated',0)} mappings revalidated","0 mappings auto-confirmed",f"{result.get('review_cases',0)} review cases"))
    return ""


def _production_scheduled_check(profile,*,cancel_event,progress):
    from ..production.scheduled import ScheduledCheckRunner
    progress(0,1,"Running scheduled-check pipeline");result=ScheduledCheckRunner(profile).run(token=cancel_event);progress(1,1,f"Scheduled check: {result.status}");return result


def _production_install_task(profile,settings,*,cancel_event,progress):
    from ..production.task_scheduler import install_validation_task
    progress(0,1,"Requesting Windows Task Scheduler validation task");result=install_validation_task(profile.root,settings);progress(1,1,"Validation task request completed");return result


def _production_search_provider(profile):
    from ..production.operations import ProductionAniListOperations
    service=ProductionAniListOperations(profile).service
    def provider(query,year,format_value,page=1):
        from ..domain.enums import MediaKind
        media_format=MediaKind(format_value) if format_value else None
        values=service.search_media(query,year=year,media_format=media_format,page=page)
        return tuple({"anilist_id":item.anilist_id,"title":resolve_display_title(TitleMetadata(item.anilist_id,item.title.english,item.title.romaji,item.title.native,item.title.primary)),"alternate_title":" / ".join(value for value in (item.title.romaji,item.title.native) if value),"format":item.media_format.value,"year":item.season_year,"status":item.status.value,"episodes":item.episode_count,"cover_url":item.cover_images.medium,"related":tuple({"anilist_id":relation.target_anilist_id,"title":relation.target_title or f"AniList {relation.target_anilist_id}","format":relation.target_format.value,"year":"","relation":relation.relation_type.value} for relation in item.relations if relation.target_anilist_id)} for item in values)
    return provider


def _production_root_settings(profile):
    from ..production.operations import configured_roots
    roots={root.library_kind.value:root.path for root in configured_roots(profile)}
    return {"test_tv_path":roots.get("TV",""),"test_movie_path":roots.get("MOVIE","")}


def _production_root_lines(profile):
    from ..production.operations import configured_roots
    return tuple(f"{root.label}: {root.path}" for root in configured_roots(profile))
