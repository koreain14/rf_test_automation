from __future__ import annotations
from typing import Any, Dict, List, Optional
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QBrush, QFont


class ResultsTableModel(QAbstractTableModel):
    HEADERS = ["Status", "Test", "Band", "Std", "Group", "Ch", "BW",
           "Margin(dB)", "Measured", "Limit", "Reason", "Key"]

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
        col = index.column()

        # -----------------------------
        # Text display
        # -----------------------------
        if role == Qt.DisplayRole:
            if col == 0:
                return r.get("status", "")
            if col == 1:
                return r.get("test_type", "")
            if col == 2:
                return r.get("band", "")
            if col == 3:
                return r.get("standard", "")
            if col == 4:
                return r.get("group", "")
            if col == 5:
                return str(r.get("channel", ""))
            if col == 6:
                return str(r.get("bw_mhz", ""))
            if col == 7:
                m = r.get("margin_db")
                return "" if m is None else f"{m:.2f}"
            if col == 8:
                v = r.get("measured_value")
                return "" if v is None else str(v)
            if col == 9:
                v = r.get("limit_value")
                return "" if v is None else str(v)
            if col == 10:
                return r.get("reason", "")
            if col == 11:
                return r.get("test_key", "") or r.get("case_key", "")

        # -----------------------------
        # Row highlight by status
        # -----------------------------
        if role == Qt.BackgroundRole:
            st = (r.get("status") or "").upper()

            if st == "FAIL":
                return QBrush(QColor("#7B1F1F"))   # deep red
            if st == "ERROR":
                return QBrush(QColor("#4A0D0D"))   # darker red
            if st == "SKIP":
                return QBrush(QColor("#78350F"))   # amber/brown
            return None

        # -----------------------------
        # Foreground / text color
        # -----------------------------
        if role == Qt.ForegroundRole:
            st = (r.get("status") or "").upper()

            if st in ("FAIL", "ERROR", "SKIP"):
                return QBrush(QColor("#F8FAFC"))   # high-contrast light text

            if col == 7:
                m = r.get("margin_db")
                if m is not None:
                    try:
                        mv = float(m)
                        if mv < 0:
                            return QBrush(QColor("#FCA5A5"))
                        elif mv < 3:
                            return QBrush(QColor("#FDE68A"))
                    except Exception:
                        pass

            return None

        # -----------------------------
        # Font emphasis
        # -----------------------------
        if role == Qt.FontRole:
            font = QFont()
            st = (r.get("status") or "").upper()
            if col == 0:
                font.setBold(True)
                return font
            if st in ("FAIL", "ERROR") and col in (0, 7, 10):
                font.setBold(True)
                return font
             
        # -----------------------------
        # Alignment
        # -----------------------------
        if role == Qt.TextAlignmentRole:
            if col in (5, 6, 7, 8, 9):
                return Qt.AlignCenter

        # -----------------------------
        # Tooltip (reason 긴 경우 보기 좋음)
        # -----------------------------
        if role == Qt.ToolTipRole:
            if col == 10:
                return r.get("reason", "")
            if col == 11:
                return r.get("test_key", "") or r.get("case_key", "")

        return None
        
    def get_row(self, row: int):
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None