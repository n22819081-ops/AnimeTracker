from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea, QTabWidget, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..data import ModernRepository
from ..widgets import AnimeTable, EmptyState, StatusBadge


class Page(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent); self.page_title=title
        self.layout=QVBoxLayout(self); self.layout.setContentsMargins(22,18,22,18); self.layout.setSpacing(12)
        heading=QLabel(title); heading.setObjectName("pageTitle"); self.layout.addWidget(heading)
        if subtitle:
            note=QLabel(subtitle); note.setObjectName("muted"); note.setWordWrap(True); self.layout.addWidget(note)


class DashboardPage(Page):
    def __init__(self, repository: ModernRepository):
        super().__init__("Dashboard","Current tracker health from the disposable modern profile.")
        self.repository=repository; self.grid=QGridLayout(); self.layout.addLayout(self.grid)
        self.warning=QLabel("Cached development data is shown. Network refresh and server scans do not run automatically.")
        self.warning.setObjectName("profileBanner"); self.layout.addWidget(self.warning)
        self.events=QListWidget(); self.events.setAccessibleName("Recent important events")
        self.layout.addWidget(QLabel("Recent important events")); self.layout.addWidget(self.events,1)
        self.refresh()

    def refresh(self):
        while self.grid.count():
            item=self.grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for index,(label,value) in enumerate(self.repository.dashboard_counts().items()):
            card=QFrame(); card.setObjectName("panel"); box=QVBoxLayout(card)
            number=QLabel(str(value)); number.setStyleSheet("font-size: 22pt; font-weight: 700;")
            title=QLabel(label); title.setWordWrap(True); title.setObjectName("muted")
            box.addWidget(number); box.addWidget(title); self.grid.addWidget(card,index//4,index%4)
        self.events.clear(); self.events.addItems(["Modern profile loaded", "Notifications remain in test mode", "Production cutover has not occurred"])


class AnimeListPage(Page):
    row_activated=Signal(object)
    def __init__(self,title,repository,predicate=lambda row: True,subtitle=""):
        super().__init__(title,subtitle); self.repository=repository; self.predicate=predicate
        controls=QHBoxLayout(); self.filter=QComboBox(); self.filter.addItems(["All","Upcoming","Currently Airing","Finished / Ready to Add","On Server","Needs Review","Partial","Complete"])
        controls.addWidget(QLabel("Filter")); controls.addWidget(self.filter); controls.addStretch(); self.layout.addLayout(controls)
        self.table=AnimeTable(); self.table.activated_row.connect(self.row_activated); self.filter.currentTextChanged.connect(self.table.set_status_filter)
        self.layout.addWidget(self.table,1); self.refresh()
    def refresh(self): self.table.set_rows([row for row in self.repository.tracked_media() if self.predicate(row)])
    def set_search(self,text): self.table.set_search(text)


class MoviesPage(AnimeListPage):
    def __init__(self,repo): super().__init__("Movies",repo,lambda r:r.media_format=="MOVIE","Availability remains Unknown unless supported by an explicit source or manual decision.")


class FranchisePage(Page):
    row_activated=Signal(object)
    def __init__(self,repo):
        super().__init__("Franchises","AniList relationships and server mappings remain separate identities."); self.repo=repo
        self.tree=QTreeWidget(); self.tree.setHeaderLabels(["Entry","Format / Year","AniList","Tracker","Mapping","Coverage"]); self.tree.setAlternatingRowColors(True)
        self.tree.itemDoubleClicked.connect(self._activate); self.layout.addWidget(self.tree,1); self.refresh()
    def refresh(self):
        self.tree.clear(); groups=defaultdict(list)
        for row in self.repo.tracked_media(): groups[(row.title.split(":")[0].split(" Season")[0],)].append(row)
        for (name,),rows in groups.items():
            parent=QTreeWidgetItem([name,"",f"{len(rows)} entries","","",""]); parent.setExpanded(False); self.tree.addTopLevelItem(parent)
            for row in rows:
                child=QTreeWidgetItem([row.title,f"{row.media_format} · {row.year or 'Unknown'}",row.anilist_status,row.tracker_status,row.mapping_label,row.coverage]); child.setData(0,Qt.UserRole,row); parent.addChild(child)
        self.tree.resizeColumnToContents(0)
    def _activate(self,item,column):
        row=item.data(0,Qt.UserRole)
        if row:self.row_activated.emit(row)


class CoveragePage(Page):
    def __init__(self,repo):
        super().__init__("Jellyfin Coverage","Read-only coverage views. No rename, move, delete, repair, or library-scan actions are available."); self.repo=repo
        self.tabs=QTabWidget(); self.by_anime=AnimeTable(); self.tabs.addTab(self.by_anime,"By anime")
        self.by_folder=QTreeWidget(); self.by_folder.setHeaderLabels(["Display target","Mapped anime","Scope","Coverage"]); self.tabs.addTab(self.by_folder,"By server folder")
        self.missing=AnimeTable(); self.tabs.addTab(self.missing,"Missing episodes"); self.layout.addWidget(self.tabs,1); self.refresh()
    def refresh(self):
        rows=self.repo.tracked_media(); self.by_anime.set_rows(rows); self.missing.set_rows([row for row in rows if row.server_status=="PARTIAL"])
        self.by_folder.clear()
        for row in rows:
            if row.mapping_label!="Not mapped": self.by_folder.addTopLevelItem(QTreeWidgetItem([row.mapping_label,row.title,row.season,row.coverage]))


class ReviewPage(Page):
    review_requested=Signal(dict)
    def __init__(self,repo):
        super().__init__("Needs Review","Only genuine ambiguity, conflicts, missing confirmed targets, and unresolved numbering appear here."); self.repo=repo
        self.list=QListWidget(); self.open=QPushButton("Review Selected"); self.open.setObjectName("primary"); self.open.clicked.connect(self._open)
        self.layout.addWidget(self.list,1); self.layout.addWidget(self.open); self.rows=(); self.refresh()
    def refresh(self):
        self.rows=self.repo.review_rows(); self.list.clear()
        for row in self.rows:self.list.addItem(f"{row['review_type'].replace('_',' ').title()} · AniList {row['anilist_id']}\n{row['evidence_json']}")
        self.open.setEnabled(bool(self.rows))
    def _open(self):
        if 0<=self.list.currentRow()<len(self.rows):self.review_requested.emit(self.rows[self.list.currentRow()])


class NotificationsPage(Page):
    def __init__(self,repo):
        super().__init__("Notifications","Test-profile outbox only. Credential values are never displayed and production delivery is disabled."); self.repo=repo
        self.tabs=QTabWidget(); self.tables={}
        for status in ("PENDING","RETRY_WAIT","DELIVERED","FAILED_PERMANENT","SUPPRESSED","CANCELED"):
            table=QTableWidget(0,7); table.setHorizontalHeaderLabels(["Event","Anime","Channel","Created","Status","Attempts","Last error"]); self.tables[status]=table; self.tabs.addTab(table,status.replace("_"," ").title())
        actions=QHBoxLayout(); self.retry=QPushButton("Retry Selected"); self.cancel=QPushButton("Cancel Pending"); self.payload=QPushButton("View Safe Payload"); self.deliveries=QPushButton("Delivery History"); self.clear=QPushButton("Clear Suppression"); self.preview=QPushButton("Generate Weekly Summary Preview"); self.preview.setToolTip("Builds a privacy-safe preview without delivery")
        for button in (self.retry,self.cancel,self.payload,self.deliveries,self.clear):button.setEnabled(False); actions.addWidget(button)
        actions.addStretch(); actions.addWidget(self.preview); self.layout.addWidget(self.tabs,1); self.layout.addLayout(actions); self.refresh()
    def refresh(self):
        for table in self.tables.values():table.setRowCount(0)
        for row in self.repo.notification_rows():
            table=self.tables.get(row["status"])
            if table is None:continue
            pos=table.rowCount(); table.insertRow(pos)
            for col,key in enumerate(("event_type","anilist_id","channel_purpose","created_at","status","attempt_count","last_error_message")):table.setItem(pos,col,QTableWidgetItem(str(row[key] or "")))


class HistoryPage(Page):
    def __init__(self,repo):
        super().__init__("History","Unified development-profile history with privacy-safe summaries."); self.repo=repo
        self.table=QTableWidget(0,3); self.table.setHorizontalHeaderLabels(["Event","Time","Source"]); self.layout.addWidget(self.table,1); self.refresh()
    def refresh(self):
        self.table.setRowCount(0)
        for row in self.repo.history_rows():
            pos=self.table.rowCount(); self.table.insertRow(pos)
            for col,key in enumerate(("occurred","occurred_at","source")):self.table.setItem(pos,col,QTableWidgetItem(str(row[key])))


class SettingsPage(Page):
    theme_changed=Signal(str); reset_requested=Signal(); preview_requested=Signal()
    def __init__(self,settings):
        super().__init__("Settings","Modern development-profile settings. Jellyfin access remains read-only and manual."); self.settings=settings
        tabs=QTabWidget(); self.layout.addWidget(tabs,1)
        appearance=QWidget(); form=QFormLayout(appearance); self.theme=QComboBox(); self.theme.addItems(["Dark","Light","Follow Windows"]); self.theme.setCurrentText(settings["theme"]); self.theme.currentTextChanged.connect(self.theme_changed); form.addRow("Theme",self.theme); tabs.addTab(appearance,"Appearance")
        jellyfin=QWidget(); jform=QFormLayout(jellyfin); self.tv=QLineEdit(settings.get("test_tv_path","")); self.movies=QLineEdit(settings.get("test_movie_path","")); jform.addRow("Test TV root",self.tv); jform.addRow("Test Movies root",self.movies); label=QLabel("Read-only access. Production roots are never scanned automatically."); label.setObjectName("muted"); jform.addRow(label); tabs.addTab(jellyfin,"Jellyfin")
        notifications=QWidget(); nform=QFormLayout(notifications)
        for label,key in (("Private Discord enabled","notifications_private_enabled"),("Shared Discord enabled","notifications_shared_enabled"),("Windows notifications enabled","notifications_windows_enabled")):
            check=QCheckBox(); check.setChecked(settings.get(key,False)); check.setEnabled(False); nform.addRow(label,check)
        nform.addRow("Private credential",QLabel("Not configured (reference only)")); nform.addRow("Shared credential",QLabel("Not configured (reference only)")); tabs.addTab(notifications,"Notifications")
        data=QWidget(); dbox=QVBoxLayout(data); preview=QPushButton("Open Legacy Import Preview"); preview.clicked.connect(self.preview_requested); reset=QPushButton("Reset Test Profile"); reset.clicked.connect(self.reset_requested); dbox.addWidget(preview); dbox.addWidget(reset); dbox.addStretch(); tabs.addTab(data,"Data and Privacy")
        for name in ("AniList","Scheduling","Backups","Diagnostics","About"):tabs.addTab(EmptyState(name,"Placeholder for a later operations milestone."),name)
