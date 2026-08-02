from __future__ import annotations

import json

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
        self.events.clear();self.events.addItems(self.repository.recent_events() or ("No recent tracker events",))


class AnimeListPage(Page):
    row_activated=Signal(object)
    def __init__(self,title,repository,predicate=lambda row: True,subtitle="",filter_options=None):
        super().__init__(title,subtitle); self.repository=repository; self.predicate=predicate
        self.filter_options=filter_options or {"All":lambda row:True}
        controls=QHBoxLayout(); self.filter=QComboBox(); self.filter.addItems(self.filter_options)
        controls.addWidget(QLabel("View")); controls.addWidget(self.filter); controls.addStretch(); self.layout.addLayout(controls)
        self.table=AnimeTable(cover_cache_dir=repository.cover_cache_dir); self.table.activated_row.connect(self.row_activated); self.filter.currentTextChanged.connect(self.refresh)
        self.layout.addWidget(self.table,1); self.refresh()
    def refresh(self,*_):
        selected=self.filter_options[self.filter.currentText()]
        self.table.set_rows([row for row in self.repository.tracked_media() if self.predicate(row) and selected(row)])
    def set_search(self,text): self.table.set_search(text)


class MoviesPage(AnimeListPage):
    def __init__(self,repo): super().__init__("Movies",repo,lambda r:r.media_format=="MOVIE","Availability remains Unknown unless supported by an explicit source or manual decision.",{
        "All":lambda r:True,"Upcoming":lambda r:r.tracker_status=="Upcoming","Theatrical only":lambda r:"Theatrical" in r.tracker_status,
        "Digitally available":lambda r:"Digital" in r.tracker_status,"On server":lambda r:r.server_status=="COMPLETE",
    })


class FranchisePage(Page):
    row_activated=Signal(object)
    def __init__(self,repo):
        super().__init__("Franchises","AniList relationships and server mappings remain separate identities."); self.repo=repo
        self.tree=QTreeWidget(); self.tree.setHeaderLabels(["Title","Relations","Format / Season","AniList Status","Server Target","Tracker Status","Season Scope","Coverage","Review"]); self.tree.setAlternatingRowColors(True)
        self.tree.itemDoubleClicked.connect(self._activate); self.layout.addWidget(self.tree,1); self.refresh()
    def refresh(self):
        self.tree.clear();rows=self.repo.tracked_media();by_id={row.anilist_id:row for row in rows};adjacency={key:set() for key in by_id}
        for row in rows:
            for relation in row.relations:
                if relation.target_anilist_id in by_id:adjacency[row.anilist_id].add(relation.target_anilist_id);adjacency[relation.target_anilist_id].add(row.anilist_id)
        groups=[];remaining=set(by_id)
        while remaining:
            start=min(remaining);component=set();pending=[start]
            while pending:
                current=pending.pop()
                if current in component:continue
                component.add(current);pending.extend(adjacency[current]-component)
            remaining-=component;groups.append([by_id[key] for key in sorted(component)])
        for rows in sorted(groups,key=lambda value:value[0].title.casefold()):
            name=rows[0].title
            parent=QTreeWidgetItem([name,f"{len(rows)} tracked entries","","","","","","",""]); parent.setExpanded(False); self.tree.addTopLevelItem(parent)
            for row in rows:
                relation="; ".join(f"{item.direction} {item.relation_type.replace('_',' ').title()}: {item.title}" for item in row.relations) or "No cached relation"
                scope=f"Season {row.mapping_label.rsplit('Season ',1)[-1]}" if "Season " in row.mapping_label else ("Movie" if row.media_format=="MOVIE" else "Unspecified")
                child=QTreeWidgetItem([row.title,relation,f"{row.media_format} · {row.season or 'No season'} {row.year or ''}",row.anilist_status,row.mapping_label,row.tracker_status,scope,row.coverage,row.review_reason or row.review or "None"]); child.setData(0,Qt.UserRole,row); parent.addChild(child)
        self.tree.resizeColumnToContents(0)
    def _activate(self,item,column):
        row=item.data(0,Qt.UserRole)
        if row:self.row_activated.emit(row)
    def set_search(self,text):
        query=text.casefold().strip()
        for index in range(self.tree.topLevelItemCount()):
            parent=self.tree.topLevelItem(index);visible=False
            for child_index in range(parent.childCount()):
                child=parent.child(child_index);match=not query or query in " ".join(child.text(column) for column in range(self.tree.columnCount())).casefold();child.setHidden(not match);visible|=match
            parent.setHidden(not visible)


class CoveragePage(Page):
    def __init__(self,repo):
        super().__init__("Jellyfin Coverage","Read-only coverage views. No rename, move, delete, repair, or library-scan actions are available."); self.repo=repo
        self.tabs=QTabWidget(); self.by_anime=QTreeWidget();self.by_anime.setHeaderLabels(["Anime","Season scope","Expected","Aired","Present","Missing","Coverage","Mapping target"]); self.tabs.addTab(self.by_anime,"By anime")
        self.by_folder=QTreeWidget(); self.by_folder.setHeaderLabels(["Folder display name","Seasons discovered","Mapped anime titles","Mapping scopes","Unmapped inventory","Ambiguous files"]); self.tabs.addTab(self.by_folder,"By server folder")
        self.missing=QTreeWidget();self.missing.setHeaderLabels(["Anime","Missing episodes","Mapping target"]);self.tabs.addTab(self.missing,"Missing episodes"); self.layout.addWidget(self.tabs,1); self.refresh()
    def refresh(self):
        rows=self.repo.tracked_media(); self.by_anime.clear();self.missing.clear();self.by_folder.clear()
        for row in rows:
            scope=(f"Season {row.mapping_label.rsplit('Season ',1)[-1]}" if "Season " in row.mapping_label else ("Movie" if row.media_format=="MOVIE" else "Unspecified"))
            self.by_anime.addTopLevelItem(QTreeWidgetItem([row.title,scope,str(row.expected_episodes or "Unknown"),str(row.aired_episodes if row.aired_episodes is not None else "Unknown"),str(row.present_episodes if row.present_episodes is not None else "Unknown"),", ".join(map(str,row.missing_episodes)) or "None known",row.coverage,row.mapping_label]))
            if row.mapping_label!="No confirmed server mapping":self.by_folder.addTopLevelItem(QTreeWidgetItem([row.mapping_label,scope,row.title,row.mapping_label,"None recorded","None recorded" if not row.review_reason else row.review_reason]))
            if row.server_status=="PARTIAL":self.missing.addTopLevelItem(QTreeWidgetItem([row.title,", ".join(map(str,row.missing_episodes)) or "Episode evidence unavailable",row.mapping_label]))
    def set_search(self,text):
        query=text.casefold().strip()
        for tree in (self.by_anime,self.by_folder,self.missing):
            for index in range(tree.topLevelItemCount()):
                item=tree.topLevelItem(index);item.setHidden(bool(query) and query not in " ".join(item.text(column) for column in range(tree.columnCount())).casefold())


class ReviewPage(Page):
    review_requested=Signal(dict)
    def __init__(self,repo):
        super().__init__("Needs Review","Only genuine ambiguity, conflicts, missing confirmed targets, and unresolved numbering appear here."); self.repo=repo
        controls=QHBoxLayout();self.type_filter=QComboBox();self.type_filter.addItem("All review types");self.severity_filter=QComboBox();self.severity_filter.addItems(["All severities","Critical","High","Medium","Low"]);controls.addWidget(self.type_filter);controls.addWidget(self.severity_filter);controls.addStretch();self.layout.addLayout(controls)
        self.list=QListWidget(); self.open=QPushButton("Review Selected"); self.open.setObjectName("primary"); self.open.clicked.connect(self._open);self.type_filter.currentTextChanged.connect(self.refresh);self.severity_filter.currentTextChanged.connect(self.refresh);self.query=""
        self.layout.addWidget(self.list,1); self.layout.addWidget(self.open); self.rows=(); self.refresh()
    def refresh(self):
        all_rows=self.repo.review_rows();types=sorted({row["review_type"].replace("_"," ").title() for row in all_rows})
        existing={self.type_filter.itemText(i) for i in range(self.type_filter.count())}
        for value in types:
            if value not in existing:self.type_filter.addItem(value)
        self.rows=tuple(row for row in all_rows if (self.type_filter.currentIndex()==0 or row["review_type"].replace("_"," ").title()==self.type_filter.currentText()) and (self.severity_filter.currentIndex()==0 or str(row["severity"]).casefold()==self.severity_filter.currentText().casefold()) and (not self.query or self.query in (row["title"]+" "+row["review_type"]+" "+str(row["anilist_id"])).casefold())); self.list.clear()
        for row in self.rows:
            season=" / ".join(value for value in (row.get("season_name") or "",str(row.get("season_year") or "")) if value)
            try:evidence="; ".join(json.loads(row.get("evidence_json") or "[]"))
            except (TypeError,ValueError):evidence=str(row.get("evidence_json") or "")
            reason=row.get("reason") or evidence or "Decision required"
            self.list.addItem(f"{row['title']}\nAniList {row['anilist_id']} · {row.get('media_format') or 'Unknown format'} · {season or 'Unknown season'}\n{row['review_type'].replace('_',' ').title()} ({row['severity']}) · {reason}")
        self.open.setEnabled(bool(self.rows))
    def set_search(self,text):self.query=text.casefold().strip();self.refresh()
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
            for col,key in enumerate(("event_type","display_title","channel_purpose","created_at","status","attempt_count","last_error_message")):table.setItem(pos,col,QTableWidgetItem(str(row[key] or "")))
    def set_search(self,text):
        query=text.casefold().strip()
        for table in self.tables.values():
            for row in range(table.rowCount()):table.setRowHidden(row,bool(query) and query not in " ".join((table.item(row,column).text() if table.item(row,column) else "") for column in range(table.columnCount())).casefold())


class HistoryPage(Page):
    def __init__(self,repo):
        super().__init__("History","Unified development-profile history with privacy-safe summaries."); self.repo=repo
        self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(["Event","Title / target","Time","Source"]); self.layout.addWidget(self.table,1); self.refresh()
    def refresh(self):
        self.table.setRowCount(0)
        for row in self.repo.history_rows():
            pos=self.table.rowCount(); self.table.insertRow(pos)
            for col,key in enumerate(("occurred","title","occurred_at","source")):self.table.setItem(pos,col,QTableWidgetItem(str(row[key])))
    def set_search(self,text):
        query=text.casefold().strip()
        for row in range(self.table.rowCount()):self.table.setRowHidden(row,bool(query) and query not in " ".join((self.table.item(row,column).text() if self.table.item(row,column) else "") for column in range(self.table.columnCount())).casefold())


class SettingsPage(Page):
    theme_changed=Signal(str); reset_requested=Signal(); preview_requested=Signal(); schedule_run_requested=Signal(); schedule_install_requested=Signal(); schedule_logs_requested=Signal()
    def __init__(self,settings,*,production=False,diagnostics=None):
        super().__init__("Settings",("Modern production settings. Jellyfin access remains read-only and explicit." if production else "Modern development-profile settings. Jellyfin access remains read-only and manual.")); self.settings=settings; self.production=production
        tabs=QTabWidget(); self.tabs=tabs; self.layout.addWidget(tabs,1)
        appearance=QWidget(); form=QFormLayout(appearance); self.theme=QComboBox(); self.theme.addItems(["Dark","Light","Follow Windows"]); self.theme.setCurrentText(settings["theme"]); self.theme.currentTextChanged.connect(self.theme_changed); form.addRow("Theme",self.theme); tabs.addTab(appearance,"Appearance")
        jellyfin=QWidget(); jform=QFormLayout(jellyfin); self.tv=QLineEdit(settings.get("test_tv_path","")); self.movies=QLineEdit(settings.get("test_movie_path","")); self.tv.setReadOnly(production); self.movies.setReadOnly(production); jform.addRow("TV root" if production else "Test TV root",self.tv); jform.addRow("Movies root" if production else "Test Movies root",self.movies); label=QLabel("Read-only access. Production roots are never scanned automatically."); label.setObjectName("muted"); jform.addRow(label); tabs.addTab(jellyfin,"Jellyfin")
        notifications=QWidget(); nform=QFormLayout(notifications);credentials={item.get("channel_purpose"):item for item in (diagnostics or {}).get("credentials",())}
        self.private_notifications=QCheckBox("Generate private Discord events");self.private_notifications.setChecked(settings.get("notifications_private_enabled",settings.get("private_notifications_enabled",False)))
        self.shared_notifications=QCheckBox("Generate shared Discord events");self.shared_notifications.setChecked(settings.get("notifications_shared_enabled",settings.get("shared_notifications_enabled",False)))
        self.windows_notifications=QCheckBox("Generate Windows notification events");self.windows_notifications.setChecked(settings.get("notifications_windows_enabled",False))
        nform.addRow("Private Discord",self.private_notifications);nform.addRow("Private credential",QLabel("Configured" if credentials.get("PRIVATE_TRACKER",{}).get("configured") else "Not configured"))
        nform.addRow("Shared Discord",self.shared_notifications);nform.addRow("Shared credential",QLabel("Configured" if credentials.get("SHARED_ANNOUNCEMENT",{}).get("configured") else "Not configured"))
        nform.addRow("Windows notifications",self.windows_notifications)
        stage=int(settings.get("notifications_stage",1));stage_label=QLabel(f"Stage {stage} · Preview Only" if stage==1 else f"Stage {stage}");stage_label.setObjectName("profileBanner" if stage==1 else "muted");nform.addRow("Delivery stage",stage_label)
        activation=QPushButton("Enable delivery");activation.setEnabled(False if stage==1 else False);activation.setToolTip("Delivery is currently in Preview Only mode. Advance notification activation to enable sending.");nform.addRow(activation)
        help_text=QLabel("Event-generation settings are saved separately. Changing them never sends a message. Delivery is currently in Preview Only mode.");help_text.setWordWrap(True);help_text.setObjectName("muted");nform.addRow(help_text);tabs.addTab(notifications,"Notifications")
        data=QWidget(); dbox=QVBoxLayout(data); preview=QPushButton("Open Legacy Import Preview"); preview.clicked.connect(self.preview_requested); reset=QPushButton("Reset Test Profile"); reset.clicked.connect(self.reset_requested); reset.setVisible(not production); dbox.addWidget(preview); dbox.addWidget(reset); dbox.addStretch(); tabs.addTab(data,"Data and Privacy")
        tabs.addTab(EmptyState("AniList","Cache-first production refresh is explicit and runs in a background worker." if production else "Placeholder for a later operations milestone."),"AniList")
        scheduling=QWidget();sform=QFormLayout(scheduling);self.schedule_enabled=QCheckBox();self.schedule_enabled.setChecked(bool(settings.get("scheduled_checks_enabled",False)));self.schedule_frequency=QComboBox();self.schedule_frequency.addItems(["Weekly","Daily"]);self.schedule_frequency.setCurrentText(settings.get("schedule_frequency","Weekly"));self.schedule_day=QComboBox();self.schedule_day.addItems(["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]);self.schedule_day.setCurrentText(settings.get("schedule_day","Sunday"));self.schedule_time=QLineEdit(settings.get("schedule_time","10:00"));self.run_missed=QCheckBox();self.run_missed.setChecked(settings.get("run_when_missed",True));self.schedule_anilist=QCheckBox();self.schedule_anilist.setChecked(settings.get("anilist_refresh_enabled",False));self.schedule_jellyfin=QCheckBox();self.schedule_jellyfin.setChecked(settings.get("jellyfin_scan_enabled",False));self.schedule_private=QCheckBox();self.schedule_private.setChecked(settings.get("private_notifications_enabled",False));self.schedule_shared=QCheckBox();self.schedule_shared.setChecked(settings.get("shared_notifications_enabled",False));self.schedule_summary=QCheckBox();self.schedule_summary.setChecked(settings.get("weekly_summaries_enabled",False));sform.addRow("Enabled",self.schedule_enabled);sform.addRow("Frequency",self.schedule_frequency);sform.addRow("Day",self.schedule_day);sform.addRow("Time",self.schedule_time);sform.addRow("Run when missed",self.run_missed);sform.addRow("AniList refresh",self.schedule_anilist);sform.addRow("Jellyfin scan",self.schedule_jellyfin);sform.addRow("Private notifications",self.schedule_private);sform.addRow("Shared announcements",self.schedule_shared);sform.addRow("Weekly summary",self.schedule_summary);sform.addRow("Task state",QLabel("Validation task not installed or not verified"));task_actions=QHBoxLayout();run_now=QPushButton("Run Scheduled Check Now");install=QPushButton("Install / Update Validation Task");logs=QPushButton("View Logs");disable=QPushButton("Disable Validation Task");disable.setEnabled(False);run_now.clicked.connect(self.schedule_run_requested);install.clicked.connect(self.schedule_install_requested);logs.clicked.connect(self.schedule_logs_requested);task_actions.addWidget(run_now);task_actions.addWidget(install);task_actions.addWidget(logs);task_actions.addWidget(disable);sform.addRow(task_actions);tabs.addTab(scheduling,"Scheduling")
        tabs.addTab(EmptyState("Backups","Verified online backups and restore validation are available through the production operations service." if production else "Placeholder for a later operations milestone."),"Backups")
        diagnostic_widget=QWidget();dform=QFormLayout(diagnostic_widget)
        for key,value in (diagnostics or {"profile_state":"Development profile","database_integrity":"Not checked","media_safety":"READ_ONLY"}).items():
            if isinstance(value,(str,int,bool)):dform.addRow(key.replace("_"," ").title(),QLabel(str(value)))
        tabs.addTab(diagnostic_widget,"Diagnostics");tabs.addTab(EmptyState("About","Anime Tracker 0.8.0 pre-release production migration." if production else "Anime Tracker development profile."),"About")
