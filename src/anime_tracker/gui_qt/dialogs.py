from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication,
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .covers import CoverImageCache
from .data import AnimeRow, ModernRepository, TitleMetadata, resolve_display_title
from .widgets import CoverageBar, StatusBadge
from .workers import BackgroundWorker
from .matching_presenter import candidate_target, confidence_tooltip, evidence_lines, evidence_summary, technical_evidence
from ..services.anilist.cancellation import CancellationToken


class AddAnimeDialog(QDialog):
    def __init__(self, search_provider=None, parent=None, *, background_search=False) -> None:
        super().__init__(parent); self.setWindowTitle("Add Anime"); self.resize(900,640); self.search_provider=search_provider or (lambda *_: ()); self.page=1; self.background_search=background_search; self.search_worker=None
        layout=QVBoxLayout(self); controls=QHBoxLayout(); self.query=QLineEdit(); self.query.setPlaceholderText("Title, AniList URL, or AniList ID")
        self.year=QSpinBox(); self.year.setRange(0,2100); self.year.setSpecialValueText("Any year")
        self.format=QComboBox(); self.format.addItems(["Any format","TV","MOVIE","OVA","ONA","SPECIAL"])
        self.search=QPushButton("Search AniList"); self.search.setObjectName("primary"); self.search.clicked.connect(self.run_search)
        controls.addWidget(self.query,1); controls.addWidget(self.year); controls.addWidget(self.format); controls.addWidget(self.search); layout.addLayout(controls)
        self.results=QTableWidget(0,7); self.results.setHorizontalHeaderLabels(["Cover","Select","Title","Romaji / Native","Format","Year","Status"]); self.results.setSelectionBehavior(QTableWidget.SelectRows); layout.addWidget(self.results,2)
        pagination=QHBoxLayout(); self.previous=QPushButton("Previous"); self.next=QPushButton("Next"); self.page_label=QLabel("Page 1"); self.previous.setEnabled(False); self.previous.clicked.connect(lambda:self.change_page(-1)); self.next.clicked.connect(lambda:self.change_page(1)); pagination.addStretch(); pagination.addWidget(self.previous); pagination.addWidget(self.page_label); pagination.addWidget(self.next); layout.addLayout(pagination)
        self.related=QListWidget(); self.related.setAccessibleName("Optional related entries"); layout.addWidget(QLabel("Related entries (optional)")); layout.addWidget(self.related,1)
        self.status=QLabel("Search to choose an exact AniList identity. Nothing is added or mapped automatically."); self.status.setObjectName("muted"); layout.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.Cancel|QDialogButtonBox.Ok); buttons.button(QDialogButtonBox.Ok).setText("Add Selected"); buttons.button(QDialogButtonBox.Ok).setEnabled(False); self.ok=buttons.button(QDialogButtonBox.Ok); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.results.itemSelectionChanged.connect(self._selection_changed)

    def run_search(self, *, keep_page=False):
        text=self.query.text().strip()
        if not text:return
        if not keep_page:self.page=1
        format_value=None if self.format.currentIndex()==0 else self.format.currentText()
        if self.background_search:
            self.search.setEnabled(False);self.status.setText("Searching AniList in the background...")
            worker=BackgroundWorker(_search_operation,self.search_provider,text,self.year.value() or None,format_value,self.page)
            worker.signals.result.connect(self._show_results);worker.signals.error.connect(self._search_error);worker.signals.finished.connect(lambda _:self.search.setEnabled(True));self.search_worker=worker;QThreadPool.globalInstance().start(worker);return
        try:
            try: results=tuple(self.search_provider(text,self.year.value() or None,format_value,page=self.page))
            except TypeError: results=tuple(self.search_provider(text,self.year.value() or None,format_value))
        except Exception:
            self.status.setText("AniList is temporarily unavailable. The entered text has been preserved."); return
        self._show_results(results)

    def _show_results(self,results):
        results=tuple(results)
        self.results.setRowCount(0); self.related.clear()
        for result in results:
            row=self.results.rowCount(); self.results.insertRow(row); self.results.setItem(row,0,QTableWidgetItem("▣")); self.results.setItem(row,1,QTableWidgetItem("○"))
            for column,key in enumerate(("title","alternate_title","format","year","status"),start=2):self.results.setItem(row,column,QTableWidgetItem(str(result.get(key,""))))
            self.results.item(row,1).setData(Qt.UserRole,result)
        self.page_label.setText(f"Page {self.page}"); self.previous.setEnabled(self.page>1); self.next.setEnabled(bool(results))
        self.status.setText("No AniList matches found." if not results else f"{len(results)} possible matches. Select one before adding.")

    def _search_error(self,kind,detail):
        self.status.setText(f"AniList is temporarily unavailable ({kind}). The entered text has been preserved.")

    def change_page(self,delta):
        self.page=max(1,self.page+delta); self.run_search(keep_page=True)

    def _selection_changed(self):
        self.related.clear(); rows=self.results.selectionModel().selectedRows(); self.ok.setEnabled(bool(rows))
        if not rows:return
        from PySide6.QtWidgets import QListWidgetItem
        selected=self.results.item(rows[0].row(),1).data(Qt.UserRole)
        for relation in selected.get("related",()):
            item=QListWidgetItem(f"{relation.get('title','Related anime')} · {relation.get('format','')} · {relation.get('year','')}")
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable); item.setCheckState(Qt.Unchecked); item.setData(Qt.UserRole,relation); self.related.addItem(item)

    def selected_entries(self):
        rows=self.results.selectionModel().selectedRows()
        if not rows:return ()
        primary=self.results.item(rows[0].row(),1).data(Qt.UserRole)
        related=tuple(self.related.item(i).data(Qt.UserRole) for i in range(self.related.count()) if self.related.item(i).checkState()==Qt.Checked)
        return (primary,*related)


class AnimeDetailDialog(QDialog):
    review_server_match_requested = Signal(object)
    view_franchise_requested = Signal(object)

    def __init__(self,row:AnimeRow,parent=None,*,details=None):
        super().__init__(parent); self.row=row;self.details=details or {}; self.setWindowTitle(row.title); self.resize(760,660)
        layout=QVBoxLayout(self); top=QHBoxLayout(); self.cover=QLabel(); self.cover.setFixedSize(150,210); self.cover.setAlignment(Qt.AlignCenter); self.cover.setObjectName("panel")
        cache_dir=getattr(getattr(parent,"repository",None),"cover_cache_dir",Path.cwd()/"cache"/"covers")
        self.cover_token=CancellationToken();self.cover_cache=CoverImageCache(cache_dir,self);self.cover.setPixmap(self.cover_cache.request(row.cover_url,self.cover_token).scaled(150,210,Qt.KeepAspectRatio,Qt.SmoothTransformation));self.cover_cache.loaded.connect(self._cover_loaded)
        info=QFormLayout(); info.addRow("Primary title",QLabel(row.title));info.addRow("English",QLabel(row.english or "Not provided by AniList")); info.addRow("Romaji",QLabel(row.romaji or "Not provided by AniList")); info.addRow("Native",QLabel(row.native or "Not provided by AniList"));info.addRow("Synonyms",QLabel(", ".join(row.synonyms) or "None provided")); info.addRow("AniList ID",QLabel(str(row.anilist_id))); info.addRow("Format",QLabel(row.media_format)); info.addRow("Season / Year",QLabel(f"{row.season or 'Not provided'} · {row.year or 'Not provided'}"));info.addRow("Episodes",QLabel(str(row.episode_count) if row.episode_count is not None else "Not provided")); top.addWidget(self.cover); top.addLayout(info,1); layout.addLayout(top)
        statuses=QHBoxLayout(); statuses.addWidget(StatusBadge(f"AniList: {row.anilist_status}")); statuses.addWidget(StatusBadge(f"Tracker: {row.tracker_status}")); statuses.addWidget(StatusBadge(f"Server: {row.server_status}")); layout.addLayout(statuses)
        tabs=QTabWidget();
        overview=QWidget(); form=QFormLayout(overview); form.addRow("Coverage",QLabel(row.coverage)); form.addRow("Next episode",QLabel(row.next_episode or "No schedule"));form.addRow("Airing time",QLabel(row.next_airing_at or "No schedule")); form.addRow("Current mapping",QLabel(row.mapping_label));form.addRow("Review reason",QLabel(row.review_reason or "No review required")); form.addRow("Decision explanation",QLabel("Provider, tracker, server, coverage, and review states are evaluated independently.")); tabs.addTab(overview,"Overview")
        history=(*self.details.get("history",()),*self.details.get("mapping_history",()))
        for name,text in (("Relations",row.relation_label or "No cached relations"),("Mapping History",_detail_lines(history,"No mapping or tracker history")),("Rejections",_detail_lines(self.details.get("rejections",()),"No rejected matches")),("Review Cases",_detail_lines(self.details.get("reviews",()),row.review_reason or row.review or "No open review")),("Notifications",_detail_lines(self.details.get("notification_preferences",()),"No per-title suppression; channel preferences remain independent"))):
            widget=QTextEdit(text); widget.setReadOnly(True); tabs.addTab(widget,name)
        layout.addWidget(tabs,1)
        actions=QGridLayout();self.action_buttons={}
        action_labels=("Refresh AniList","View Franchise","Review Server Match","Mark Not on Server","Suppress Auto-Match","Restore Auto-Match","Archive","Restore","Open AniList Page","Copy Title","Show Full Path","Export Diagnostics")
        for index,label in enumerate(action_labels):
            button=QPushButton(label); button.setEnabled(label in {"Copy Title","View Franchise","Review Server Match"});self.action_buttons[label]=button;actions.addWidget(button,index//4,index%4)
        self.action_buttons["Review Server Match"].clicked.connect(lambda:self.review_server_match_requested.emit(self.row))
        self.action_buttons["View Franchise"].clicked.connect(lambda:self.view_franchise_requested.emit(self.row))
        self.action_buttons["Copy Title"].clicked.connect(lambda:QApplication.clipboard().setText(self.row.title))
        layout.addLayout(actions); close=QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(self.reject); layout.addWidget(close)

    def _cover_loaded(self,url,pixmap):
        if url==self.row.cover_url:self.cover.setPixmap(pixmap.scaled(150,210,Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def closeEvent(self,event):
        self.cover_token.cancel();self.cover_cache.cancel_pending();super().closeEvent(event)


class MatchingReviewDialog(QDialog):
    mark_not_on_server_requested = Signal(dict)
    suppress_auto_match_requested = Signal(dict)
    confirm_candidate_requested = Signal(dict,dict)
    reject_candidate_requested = Signal(dict,dict)

    def __init__(self,review:dict,parent=None):
        super().__init__(parent); self.review=review; self.setWindowTitle("Review Server Match"); self.resize(980,680); self._prepared_candidates=tuple(review.get("candidates",()))
        layout=QVBoxLayout(self); layout.addWidget(QLabel(f"{review.get('title') or 'Tracked anime'}\nAniList {review.get('anilist_id','')} · {review.get('media_format','Unknown')} · {review.get('season_name') or ''} {review.get('season_year') or ''}\nTracker: {review.get('tracker_status') or 'Unknown'} · Server: {review.get('server_status') or 'Unknown'}"))
        explanation=QLabel(f"Why this item needs review: {review.get('reason') or review.get('review_type','Decision required').replace('_',' ').title()}"); explanation.setWordWrap(True); layout.addWidget(explanation)
        mapping=QLabel(f"Current mapping: {review.get('current_mapping') or 'No confirmed server mapping'}");mapping.setWordWrap(True);layout.addWidget(mapping)
        self.candidates=QTableWidget(0,5); self.candidates.setHorizontalHeaderLabels(["Suggested target","Confidence","Match points","Evidence summary","Exact Jellyfin path"]); self.candidates.setSelectionBehavior(QAbstractItemView.SelectRows); self.candidates.setSelectionMode(QAbstractItemView.SingleSelection); self.candidates.setWordWrap(False); self.candidates.setTextElideMode(Qt.ElideRight)
        header=self.candidates.horizontalHeader(); header.setSectionResizeMode(QHeaderView.Interactive)
        for column,width in enumerate((260,130,100,310,360)):self.candidates.setColumnWidth(column,width)
        self.candidates.horizontalHeaderItem(2).setToolTip("Additive points used to rank candidates. This value is not a percentage.")
        layout.addWidget(self.candidates,1)
        for candidate in self._prepared_candidates:
            pos=self.candidates.rowCount(); self.candidates.insertRow(pos)
            values=(candidate_target(candidate),candidate.get("confidence") or "",candidate.get("score") if candidate.get("score") is not None else "",evidence_summary(candidate),candidate.get("relative_path") or "")
            for col,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setToolTip(confidence_tooltip(value) if col==1 else str(value));self.candidates.setItem(pos,col,item)
        self.details=QTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(150); self.details.setPlaceholderText("Select a candidate to see its season scope and full evidence."); layout.addWidget(self.details)
        self.technical_toggle=QCheckBox("Show technical evidence"); self.technical_toggle.setToolTip("Shows the stored structured evidence for diagnostics."); layout.addWidget(self.technical_toggle)
        self.technical_details=QTextEdit(); self.technical_details.setReadOnly(True); self.technical_details.setMaximumHeight(140); self.technical_details.hide(); layout.addWidget(self.technical_details)
        self.candidates.itemSelectionChanged.connect(self._candidate_selected); self.technical_toggle.toggled.connect(self._technical_toggled)
        has_candidates=self.candidates.rowCount()>0
        if not has_candidates:
            self.candidates.hide(); self.empty_candidate_message=QLabel("No Jellyfin candidate was found for this title.\n\nThis title may not be on the server, or the folder name may be too different for automatic matching."); self.empty_candidate_message.setWordWrap(True); self.empty_candidate_message.setObjectName("panel"); layout.addWidget(self.empty_candidate_message,1)
        else:self.empty_candidate_message=None
        if has_candidates:self.candidates.selectRow(0)
        self.stale=bool(review.get("stale")); self.notice=QLabel("Candidate is stale and must be regenerated." if self.stale else ("Choose an explicit action. No mapping is confirmed automatically." if has_candidates else "No candidate is required to mark this title as not on the server.")); self.notice.setObjectName("profileBanner" if self.stale else "muted"); layout.addWidget(self.notice)
        buttons=QDialogButtonBox(); self.confirm=None; self.reject_candidate=None
        if has_candidates:
            self.confirm=buttons.addButton("Confirm Suggestion",QDialogButtonBox.ActionRole); self.confirm.setEnabled(not self.stale); self.reject_candidate=buttons.addButton("Reject Candidate",QDialogButtonBox.DestructiveRole)
            self.confirm.clicked.connect(self._confirm_selected);self.reject_candidate.clicked.connect(self._reject_selected)
        self.choose_folder=buttons.addButton("Choose Folder Manually",QDialogButtonBox.ActionRole); self.choose_folder.setEnabled(False); self.choose_folder.setToolTip("Manual folder selection is not available in this packaged build.")
        self.mark_not_on_server=buttons.addButton("Mark Not on Server",QDialogButtonBox.ActionRole); self.suppress_auto_match=buttons.addButton("Suppress Automatic Matching",QDialogButtonBox.ActionRole); buttons.addButton(QDialogButtonBox.Cancel)
        self.mark_not_on_server.clicked.connect(lambda:self.mark_not_on_server_requested.emit(self.review)); self.suppress_auto_match.clicked.connect(lambda:self.suppress_auto_match_requested.emit(self.review)); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def show_action_error(self,message:str)->None:
        self.notice.setText(message);self.notice.setObjectName("profileBanner");self.notice.style().unpolish(self.notice);self.notice.style().polish(self.notice)

    def _selected_candidate(self):
        rows=self.candidates.selectionModel().selectedRows()
        return self._prepared_candidates[rows[0].row()] if rows else None

    def _confirm_selected(self):
        candidate=self._selected_candidate()
        if candidate is not None and not self.stale:self.confirm_candidate_requested.emit(self.review,candidate)

    def _reject_selected(self):
        candidate=self._selected_candidate()
        if candidate is not None:self.reject_candidate_requested.emit(self.review,candidate)

    def _candidate_selected(self):
        candidate=self._selected_candidate()
        if candidate is None:self.details.clear();self.technical_details.clear();return
        conflict="None" if str(candidate.get("confidence") or "") not in {"CONFLICTING","REJECTED","INSUFFICIENT_EVIDENCE"} else str(candidate.get("confidence")).replace("_"," ").title()
        self.details.setPlainText("\n".join((f"Suggested target: {candidate_target(candidate)}",f"Parent folder: {candidate.get('display_name') or candidate.get('relative_path') or 'Unknown'}",f"Season scope: {('Season '+format(int(candidate['season_number']),'02d')) if candidate.get('season_number') is not None else 'Not season-scoped'}",f"Confidence: {candidate.get('confidence') or 'Unknown'}",f"Match points: {candidate.get('score') if candidate.get('score') is not None else 'Not available'}",f"Conflict: {conflict}","Evidence:",*(f"- {line}" for line in evidence_lines(candidate)))))
        self.technical_details.setPlainText(technical_evidence(candidate))

    def _technical_toggled(self,visible:bool):
        self.technical_details.setVisible(visible)


class LegacyImportPreviewDialog(QDialog):
    def __init__(self,repository:ModernRepository,parent=None):
        super().__init__(parent); self.setWindowTitle("Legacy Import Preview"); self.resize(640,480); counts=repository.import_preview()
        layout=QVBoxLayout(self); heading=QLabel("Read-only migration comparison"); heading.setObjectName("pageTitle"); layout.addWidget(heading)
        table=QTableWidget(0,2); table.setHorizontalHeaderLabels(["Category","Rows"])
        for label,key in (("Active tracked titles","active_titles"),("Archived / orphaned rows","archived_orphans"),("Shared baseline rows","baseline_rows"),("Mappings","mappings"),("Rejections","rejections"),("Candidates","candidates")):
            row=table.rowCount(); table.insertRow(row); table.setItem(row,0,QTableWidgetItem(label)); table.setItem(row,1,QTableWidgetItem(str(counts[key])))
        layout.addWidget(table); warning=QLabel("Preview only. Production cutover is disabled and the live database is not modified."); warning.setObjectName("profileBanner"); warning.setWordWrap(True); layout.addWidget(warning)
        buttons=QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(self.reject); layout.addWidget(buttons)


def _search_operation(provider,text,year,format_value,page,*,cancel_event,progress):
    if cancel_event.is_set():return ()
    progress(0,1,"Searching AniList")
    try:results=tuple(provider(text,year,format_value,page=page))
    except TypeError:results=tuple(provider(text,year,format_value))
    progress(1,1,f"Found {len(results)} matches");return results


def _detail_lines(values,empty):
    if not values:return empty
    return "\n\n".join(" · ".join(f"{key.replace('_',' ').title()}: {value}" for key,value in item.items() if value not in (None,"",[],{})) for item in values)
