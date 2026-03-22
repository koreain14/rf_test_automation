from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class CaseTableModel(QAbstractTableModel):
    HEADERS = [
        "Test",
        "Band",
        "Standard",
        "Mode",
        "CH",
        "Freq (MHz)",
        "BW",
        "Key",
    ]

    def __init__(self, rows: List[Dict[str, Any]] | None = None, parent=None):
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = list(rows or [])

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role != Qt.DisplayRole:
            return None

        values = [
            row.get("test_type", ""),
            row.get("band", ""),
            row.get("standard", ""),
            row.get("phy_mode", row.get("mode", "")),
            row.get("channel", ""),
            row.get("frequency_mhz", row.get("center_freq_mhz", "")),
            row.get("bandwidth_mhz", row.get("bw_mhz", "")),
            row.get("case_key", row.get("key", row.get("id", ""))),
        ]
        return values[col] if 0 <= col < len(values) else None

    def setData(self, index, value, role=Qt.EditRole):
        return False

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = [dict(r) for r in (rows or [])]
        self.endResetModel()

    def append_rows(self, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        start = len(self._rows)
        end = start + len(rows) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._rows.extend(dict(r) for r in rows)
        self.endInsertRows()

    def clear(self) -> None:
        self.set_rows([])

    def row_at(self, row: int) -> Dict[str, Any] | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rows(self) -> List[Dict[str, Any]]:
        return list(self._rows)


class GroupSummaryTableModel(QAbstractTableModel):
    HEADERS = ["Band", "Standard", "BW", "Test", "Total", "Enabled", "Disabled"]

    def __init__(self, rows: List[Any] | None = None, parent=None):
        super().__init__(parent)
        self._rows: List[Any] = list(rows or [])

    def set_rows(self, rows: List[Any]) -> None:
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def clear(self) -> None:
        self.set_rows([])

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role != Qt.DisplayRole:
            return None
        values = [
            getattr(row, "band", ""),
            getattr(row, "standard", ""),
            getattr(row, "bandwidth_mhz", 0),
            getattr(row, "test_type", ""),
            getattr(row, "total_count", 0),
            getattr(row, "enabled_count", 0),
            getattr(row, "disabled_count", 0),
        ]
        return values[index.column()] if 0 <= index.column() < len(values) else None

    def row_at(self, row: int):
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None
