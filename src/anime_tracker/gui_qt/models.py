from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from .data import AnimeRow


COLUMNS = (
    ("Cover", "cover_url"), ("Title", "title"), ("Format", "media_format"), ("Season", "season"), ("Year", "year"),
    ("AniList Status", "anilist_status"), ("Tracker Status", "tracker_status"),
    ("Server Status", "server_status"), ("Coverage", "coverage"), ("Next Episode", "next_episode"),
    ("Review", "review"), ("Last Updated", "last_updated"),
)


class AnimeTableModel(QAbstractTableModel):
    def __init__(self, rows=(), parent=None) -> None:
        super().__init__(parent)
        self.rows: list[AnimeRow] = list(rows)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        value = getattr(row, COLUMNS[index.column()][1])
        if role in {Qt.DisplayRole, Qt.ToolTipRole}:
            if index.column() == 0:
                return "Cover" if value else "No cover"
            return "" if value is None else str(value).replace("_", " ").title() if index.column() in {2,5,6,7,10} else str(value)
        if role == Qt.UserRole:
            return row
        if role == Qt.TextAlignmentRole and index.column() in {0,3,4,9}:
            return Qt.AlignCenter
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section][0]
        return super().headerData(section, orientation, role)

    def set_rows(self, rows) -> None:
        self.beginResetModel(); self.rows = list(rows); self.endResetModel()

    def update_row(self, updated: AnimeRow) -> None:
        for index, row in enumerate(self.rows):
            if row.anilist_id == updated.anilist_id:
                self.rows[index] = updated
                self.dataChanged.emit(self.index(index, 0), self.index(index, len(COLUMNS)-1))
                return
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows)); self.rows.append(updated); self.endInsertRows()


class AnimeFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.query = ""
        self.status_filter = "All"
        self.setSortCaseSensitivity(Qt.CaseInsensitive)

    def set_search(self, query: str) -> None:
        self.beginFilterChange(); self.query = query.casefold().strip(); self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_status_filter(self, status: str) -> None:
        self.beginFilterChange(); self.status_filter = status; self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        model = self.sourceModel()
        row = model.rows[source_row]
        if self.query and not all(token in row.searchable for token in self.query.split()):
            return False
        if self.status_filter == "All":
            return True
        return self.status_filter.casefold() in {row.tracker_status.casefold(), row.server_status.casefold(), row.review.casefold()}
