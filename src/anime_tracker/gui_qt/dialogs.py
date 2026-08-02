from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .data import AnimeRow, ModernRepository
from .widgets import CoverageBar, StatusBadge


class AddAnimeDialog(QDialog):
    def __init__(self, search_provider=None, parent=None) -> None:
        super().__init__(parent); self.setWindowTitle("Add Anime"); self.resize(900,640); self.search_provider=search_provider or (lambda *_: ()); self.page=1
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
        try:
            format_value=None if self.format.currentIndex()==0 else self.format.currentText()
            try: results=tuple(self.search_provider(text,self.year.value() or None,format_value,page=self.page))
            except TypeError: results=tuple(self.search_provider(text,self.year.value() or None,format_value))
        except Exception:
            self.status.setText("AniList is temporarily unavailable. The entered text has been preserved."); return
        self.results.setRowCount(0); self.related.clear()
        for result in results:
            row=self.results.rowCount(); self.results.insertRow(row); self.results.setItem(row,0,QTableWidgetItem("▣")); self.results.setItem(row,1,QTableWidgetItem("○"))
            for column,key in enumerate(("title","alternate_title","format","year","status"),start=2):self.results.setItem(row,column,QTableWidgetItem(str(result.get(key,""))))
            self.results.item(row,1).setData(Qt.UserRole,result)
        self.page_label.setText(f"Page {self.page}"); self.previous.setEnabled(self.page>1); self.next.setEnabled(bool(results))
        self.status.setText("No AniList matches found." if not results else f"{len(results)} possible matches. Select one before adding.")

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
    def __init__(self,row:AnimeRow,parent=None):
        super().__init__(parent); self.row=row; self.setWindowTitle(row.title); self.resize(760,660)
        layout=QVBoxLayout(self); top=QHBoxLayout(); cover=QLabel("Cover\nplaceholder"); cover.setFixedSize(150,210); cover.setAlignment(Qt.AlignCenter); cover.setObjectName("panel")
        info=QFormLayout(); info.addRow("Primary title",QLabel(row.title)); info.addRow("Romaji",QLabel(row.romaji or "Unknown")); info.addRow("Native",QLabel(row.native or "Unknown")); info.addRow("AniList ID",QLabel(str(row.anilist_id))); info.addRow("Format",QLabel(row.media_format)); info.addRow("Season / Year",QLabel(f"{row.season or 'Unknown'} · {row.year or 'Unknown'}")); top.addWidget(cover); top.addLayout(info,1); layout.addLayout(top)
        statuses=QHBoxLayout(); statuses.addWidget(StatusBadge(f"AniList: {row.anilist_status}")); statuses.addWidget(StatusBadge(f"Tracker: {row.tracker_status}")); statuses.addWidget(StatusBadge(f"Server: {row.server_status}")); layout.addLayout(statuses)
        tabs=QTabWidget();
        overview=QWidget(); form=QFormLayout(overview); form.addRow("Coverage",QLabel(row.coverage)); form.addRow("Next episode",QLabel(row.next_episode or "No schedule")); form.addRow("Current mapping",QLabel(row.mapping_label)); form.addRow("Decision explanation",QLabel("Provider, tracker, server, coverage, and review states are evaluated independently.")); tabs.addTab(overview,"Overview")
        for name,text in (("Relations",row.relation_label or "No cached relations"),("Mapping History","History is preserved in the modern repository."),("Rejections","No active rejection details loaded."),("Review Cases",row.review or "No open review"),("Notifications","Per-title private/shared suppressions remain separate.")):
            widget=QTextEdit(text); widget.setReadOnly(True); tabs.addTab(widget,name)
        layout.addWidget(tabs,1)
        actions=QGridLayout()
        action_labels=("Refresh AniList","View Franchise","Review Server Match","Mark Not on Server","Suppress Auto-Match","Restore Auto-Match","Archive","Restore","Open AniList Page","Copy Title","Show Full Path","Export Diagnostics")
        for index,label in enumerate(action_labels):
            button=QPushButton(label); button.setEnabled(label in {"Copy Title","View Franchise","Review Server Match"}); actions.addWidget(button,index//4,index%4)
        layout.addLayout(actions); close=QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(self.reject); layout.addWidget(close)


class MatchingReviewDialog(QDialog):
    def __init__(self,review:dict,parent=None):
        super().__init__(parent); self.review=review; self.setWindowTitle("Review Server Match"); self.resize(780,600)
        layout=QVBoxLayout(self); layout.addWidget(QLabel(f"AniList Entry: {review.get('title') or 'Tracked anime'}"))
        explanation=QLabel(str(review.get("evidence_json") or review.get("evidence") or "Review the candidate evidence below before making a decision.")); explanation.setWordWrap(True); layout.addWidget(explanation)
        self.candidates=QTableWidget(0,4); self.candidates.setHorizontalHeaderLabels(["Target","Confidence","Score","Evidence"]); layout.addWidget(self.candidates,1)
        for candidate in review.get("candidates",()):
            pos=self.candidates.rowCount(); self.candidates.insertRow(pos)
            for col,key in enumerate(("target","confidence","score","evidence")):self.candidates.setItem(pos,col,QTableWidgetItem(str(candidate.get(key,""))))
        self.stale=bool(review.get("stale")); self.notice=QLabel("Candidate is stale and must be regenerated." if self.stale else "Manual confirmation is required. Suggestions are never auto-confirmed."); self.notice.setObjectName("profileBanner" if self.stale else "muted"); layout.addWidget(self.notice)
        buttons=QDialogButtonBox(); self.confirm=buttons.addButton("Confirm Suggestion",QDialogButtonBox.AcceptRole); self.confirm.setEnabled(not self.stale and self.candidates.rowCount()>0); buttons.addButton("Choose Different Target",QDialogButtonBox.ActionRole); buttons.addButton("Reject Candidate",QDialogButtonBox.DestructiveRole); buttons.addButton("Mark Not on Server",QDialogButtonBox.ActionRole); buttons.addButton("Suppress Auto-Match",QDialogButtonBox.ActionRole); buttons.addButton(QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)


class LegacyImportPreviewDialog(QDialog):
    def __init__(self,repository:ModernRepository,parent=None):
        super().__init__(parent); self.setWindowTitle("Legacy Import Preview"); self.resize(640,480); counts=repository.import_preview()
        layout=QVBoxLayout(self); heading=QLabel("Read-only migration comparison"); heading.setObjectName("pageTitle"); layout.addWidget(heading)
        table=QTableWidget(0,2); table.setHorizontalHeaderLabels(["Category","Rows"])
        for label,key in (("Active tracked titles","active_titles"),("Archived / orphaned rows","archived_orphans"),("Shared baseline rows","baseline_rows"),("Mappings","mappings"),("Rejections","rejections"),("Candidates","candidates")):
            row=table.rowCount(); table.insertRow(row); table.setItem(row,0,QTableWidgetItem(label)); table.setItem(row,1,QTableWidgetItem(str(counts[key])))
        layout.addWidget(table); warning=QLabel("Preview only. Production cutover is disabled and the live database is not modified."); warning.setObjectName("profileBanner"); warning.setWordWrap(True); layout.addWidget(warning)
        buttons=QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
