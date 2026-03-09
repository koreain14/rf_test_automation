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
        # Background highlight by status
        # -----------------------------
        if role == Qt.BackgroundRole:
            st = (r.get("status") or "").upper()

            if st == "FAIL":
                return QBrush(QColor("#FFF1F1"))   # 매우 연한 빨강
            if st == "ERROR":
                return QBrush(QColor("#FFE5E5"))   # FAIL보다 조금 더 강한 빨강
            if st == "SKIP":
                return QBrush(QColor("#FFFBEA"))   # 연한 베이지/노랑

            # PASS / 기타는 기본 배경 유지
            return None

        # -----------------------------
        # Foreground highlight
        # -----------------------------
        if role == Qt.ForegroundRole:
            st = (r.get("status") or "").upper()

            # 상태 텍스트 강조
            if st == "FAIL":
                if col == 0:
                    return QBrush(QColor("#C62828"))  # 상태 컬럼은 더 진하게
            elif st == "ERROR":
                if col == 0:
                    return QBrush(QColor("#8E0000"))
            elif st == "SKIP":
                if col == 0:
                    return QBrush(QColor("#8A6D1D"))

            # margin 강조 (margin 컬럼만)
            if col == 7:
                m = r.get("margin_db")
                if m is not None:
                    try:
                        mv = float(m)
                        if mv < 0:
                            return QBrush(QColor("#C62828"))   # 음수 margin
                        elif mv < 3:
                            return QBrush(QColor("#B26A00"))   # 작은 margin
                    except Exception:
                        pass

            return None
        
        # -----------------------------
        # Status column bold
        # -----------------------------
        
        if role == Qt.FontRole:
            if col == 0:  # Status 컬럼
                font = QFont()
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