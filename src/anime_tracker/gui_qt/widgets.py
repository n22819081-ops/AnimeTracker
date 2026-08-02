from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton,
    QTableView, QVBoxLayout, QWidget,
)

from .models import AnimeFilterProxy, AnimeTableModel
from .covers import CoverDelegate


class StatusBadge(QLabel):
    def __init__(self, text: str = "Unknown", parent=None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(8, 3, 8, 3)
        self.setAccessibleName(f"Status: {text}")
        self.set_status(text)

    def set_status(self, text: str) -> None:
        self.setText(text)
        key = text.casefold()
        color = "#55c58a" if any(word in key for word in ("complete","on server","finished")) else "#e5b85c" if any(word in key for word in ("airing","partial","review","upcoming")) else "#ef6f6c" if any(word in key for word in ("missing","failed","cancel")) else "#788391"
        self.setStyleSheet(f"QLabel {{ background: {color}; color: #111317; border-radius: 4px; font-weight: 700; }}")


class CoverageBar(QWidget):
    def __init__(self, present: int = 0, expected: int = 0, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.bar = QProgressBar(); self.label = QLabel()
        layout.addWidget(self.bar, 1); layout.addWidget(self.label)
        self.set_coverage(present, expected)

    def set_coverage(self, present: int, expected: int) -> None:
        self.bar.setRange(0, max(expected, 1)); self.bar.setValue(present)
        self.label.setText(f"{present}/{expected}" if expected else "Unknown")
        self.setAccessibleName(f"Coverage {self.label.text()}")


class EmptyState(QFrame):
    def __init__(self, title="Nothing here", detail="No items match the current view.", parent=None) -> None:
        super().__init__(parent); self.setObjectName("panel")
        layout=QVBoxLayout(self); layout.setAlignment(Qt.AlignCenter)
        heading=QLabel(title); heading.setStyleSheet("font-size: 14pt; font-weight: 700;")
        body=QLabel(detail); body.setObjectName("muted"); body.setWordWrap(True); body.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading); layout.addWidget(body)


class AnimeTable(QWidget):
    activated_row = Signal(object)

    def __init__(self, rows=(), parent=None, *, cover_cache_dir=None) -> None:
        super().__init__(parent)
        self.model = AnimeTableModel(rows, self)
        self.proxy = AnimeFilterProxy(self); self.proxy.setSourceModel(self.model)
        self.view = QTableView(); self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True); self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows); self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers); self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.verticalHeader().setVisible(False); self.view.horizontalHeader().setStretchLastSection(True)
        if cover_cache_dir is not None:
            self.cover_delegate=CoverDelegate(cover_cache_dir,self.view);self.view.setItemDelegateForColumn(0,self.cover_delegate)
            self.view.verticalHeader().setDefaultSectionSize(82);self.view.setColumnWidth(0,72)
        self.view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.horizontalHeader().customContextMenuRequested.connect(self._column_menu)
        self.view.doubleClicked.connect(self._activate); self.view.customContextMenuRequested.connect(self._context_menu)
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.addWidget(self.view)
        self.empty = EmptyState(); self.empty.hide(); layout.addWidget(self.empty)
        self._sync_empty()

    def set_rows(self, rows) -> None:
        selected = self.selected_anilist_id()
        self.model.set_rows(rows); self._sync_empty()
        if selected is not None:
            self.select_anilist_id(selected)

    def set_search(self, text: str) -> None:
        self.proxy.set_search(text); self._sync_empty()

    def set_status_filter(self, value: str) -> None:
        self.proxy.set_status_filter(value); self._sync_empty()

    def selected_anilist_id(self):
        indexes=self.view.selectionModel().selectedRows()
        return indexes[0].data(Qt.UserRole).anilist_id if indexes else None

    def select_anilist_id(self, anilist_id: int) -> None:
        for source_row,row in enumerate(self.model.rows):
            if row.anilist_id == anilist_id:
                proxy_index=self.proxy.mapFromSource(self.model.index(source_row,0))
                if proxy_index.isValid(): self.view.selectRow(proxy_index.row())
                return

    def selected_row(self):
        indexes=self.view.selectionModel().selectedRows()
        return indexes[0].data(Qt.UserRole) if indexes else None

    def _activate(self, index) -> None:
        row=index.data(Qt.UserRole)
        if row: self.activated_row.emit(row)

    def _context_menu(self, position) -> None:
        if not self.selected_row(): return
        menu=QMenu(self); details=menu.addAction("Open Details"); copy=menu.addAction("Copy Title")
        chosen=menu.exec(self.view.viewport().mapToGlobal(position))
        if chosen==details: self.activated_row.emit(self.selected_row())
        elif chosen==copy:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self.selected_row().title)

    def _column_menu(self, position) -> None:
        menu=QMenu(self)
        for column in range(self.model.columnCount()):
            action=menu.addAction(str(self.model.headerData(column,Qt.Horizontal))); action.setCheckable(True); action.setChecked(not self.view.isColumnHidden(column)); action.setData(column)
        selected=menu.exec(self.view.horizontalHeader().mapToGlobal(position))
        if selected is not None:self.view.setColumnHidden(int(selected.data()),not selected.isChecked())

    def _sync_empty(self) -> None:
        empty=self.proxy.rowCount()==0
        self.view.setVisible(not empty); self.empty.setVisible(empty)
