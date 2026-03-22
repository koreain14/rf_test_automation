from __future__ import annotations
from typing import Any, Dict, List

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class StepLogModel(QAbstractTableModel):
    HEADERS = ["Step", "Status", "Artifact", "Data"]

    def __init__(self):
        super().__init__()
        self._rows: List[Dict[str, Any]] = []

    def set_rows(self, rows: List[Dict[str, Any]]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        if role == Qt.DisplayRole:
            c = index.column()
            if c == 0: return r.get("step_name", "")
            if c == 1: return r.get("status", "")
            if c == 2: return r.get("artifact_uri", "") or ""
            if c == 3: return r.get("display_data", str(r.get("data", {})))
        return None