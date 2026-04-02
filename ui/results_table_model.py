from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QBrush, QFont

from application.result_difference import format_difference, format_difference_value, format_numeric_value


class ResultsTableModel(QAbstractTableModel):
    HEADERS = [
        "Status",
        "Test",
        "Band",
        "BW",
        "CH",
        "Voltage Cond",
        "Voltage (V)",
        "Measured",
        "Limit",
        "Difference",
        "Unit",
        "Screenshot",
    ]

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

        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return row.get("status", "")
            if col == 1:
                return row.get("test_type", "")
            if col == 2:
                return row.get("band", "")
            if col == 3:
                return str(row.get("bw_mhz", ""))
            if col == 4:
                return str(row.get("channel", ""))
            if col == 5:
                return row.get("voltage_condition", "")
            if col == 6:
                return self._format_voltage(row.get("target_voltage_v"))
            if col == 7:
                value = row.get("measured_value")
                return format_numeric_value(value)
            if col == 8:
                value = row.get("limit_value")
                return format_numeric_value(value)
            if col == 9:
                return format_difference_value(row.get("difference_value"))
            if col == 10:
                return row.get("measurement_unit", "") or row.get("difference_unit", "")
            if col == 11:
                return "Yes" if row.get("has_screenshot") else ""

        if role == Qt.UserRole:
            if col == 0:
                return str(row.get("status", ""))
            if col == 1:
                return str(row.get("test_type", ""))
            if col == 2:
                return str(row.get("band", ""))
            if col == 3:
                return self._as_sortable_number(row.get("bw_mhz"))
            if col == 4:
                return self._as_sortable_number(row.get("channel"))
            if col == 5:
                return str(row.get("voltage_condition", ""))
            if col == 6:
                return self._as_sortable_number(row.get("target_voltage_v"))
            if col == 7:
                return self._as_sortable_number(row.get("measured_value"))
            if col == 8:
                return self._as_sortable_number(row.get("limit_value"))
            if col == 9:
                return self._as_sortable_number(row.get("difference_value"))
            if col == 10:
                return str(row.get("measurement_unit", "") or row.get("difference_unit", ""))
            if col == 11:
                return 1 if row.get("has_screenshot") else 0

        if role == Qt.BackgroundRole:
            status = str(row.get("status", "")).upper()
            if status == "FAIL":
                return QBrush(QColor("#7B1F1F"))
            if status == "ERROR":
                return QBrush(QColor("#4A0D0D"))
            if status == "SKIP":
                return QBrush(QColor("#78350F"))
            return None

        if role == Qt.ForegroundRole:
            status = str(row.get("status", "")).upper()
            if status in ("FAIL", "ERROR", "SKIP"):
                return QBrush(QColor("#F8FAFC"))

            if col == 9:
                value = row.get("difference_value")
                try:
                    numeric = float(value)
                    if numeric > 0:
                        return QBrush(QColor("#FCA5A5"))
                    if numeric > -3:
                        return QBrush(QColor("#FDE68A"))
                except Exception:
                    pass
            return None

        if role == Qt.FontRole:
            font = QFont()
            status = str(row.get("status", "")).upper()
            if col == 0:
                font.setBold(True)
                return font
            if status in ("FAIL", "ERROR") and col in (0, 9, 11):
                font.setBold(True)
                return font

        if role == Qt.TextAlignmentRole:
            if col in (3, 4, 5, 6, 7, 8, 9, 10, 11):
                return Qt.AlignCenter

        if role == Qt.ToolTipRole:
            if col == 9:
                return format_difference(row.get("difference_value"), row.get("difference_unit", ""))
            if col == 11:
                return row.get("screenshot_path", "") or row.get("screenshot_abs_path", "")
            details = [
                f"Key: {row.get('test_key', '')}",
                f"Reason: {row.get('reason', '')}",
            ]
            return "\n".join(part for part in details if part.strip())

        return None

    def get_row(self, row: int):
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:
        reverse = order == Qt.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=lambda row: self._sort_key(row, column), reverse=reverse)
        self.layoutChanged.emit()

    def _sort_key(self, row: Dict[str, Any], column: int):
        if column == 0:
            return str(row.get("status", ""))
        if column == 1:
            return str(row.get("test_type", ""))
        if column == 2:
            return str(row.get("band", ""))
        if column == 3:
            return self._as_sortable_number(row.get("bw_mhz"))
        if column == 4:
            return self._as_sortable_number(row.get("channel"))
        if column == 5:
            return str(row.get("voltage_condition", ""))
        if column == 6:
            return self._as_sortable_number(row.get("target_voltage_v"))
        if column == 7:
            return self._as_sortable_number(row.get("measured_value"))
        if column == 8:
            return self._as_sortable_number(row.get("limit_value"))
        if column == 9:
            return self._as_sortable_number(row.get("difference_value"))
        if column == 10:
            return str(row.get("measurement_unit", "") or row.get("difference_unit", ""))
        if column == 11:
            return 1 if row.get("has_screenshot") else 0
        return ""

    def _as_sortable_number(self, value: Any) -> float:
        try:
            if value in (None, ""):
                return float("-inf")
            return float(value)
        except Exception:
            return float("-inf")

    def _format_voltage(self, value: Any) -> str:
        try:
            if value in (None, ""):
                return ""
            return f"{float(value):g}"
        except Exception:
            return str(value or "")
