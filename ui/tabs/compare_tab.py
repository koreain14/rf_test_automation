from __future__ import annotations

import logging
from typing import Callable, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from application.result_difference import format_difference, format_difference_value, format_numeric_value
from ui.tabs.result_export_helper import ResultExportHelper
from ui.tabs.result_task_tab_base import ResultTaskTabBase


log = logging.getLogger(__name__)


class CompareTab(QWidget, ResultTaskTabBase):
    def __init__(self, service, get_project_id: Callable[[], str | None], parent=None):
        super().__init__(parent)
        self.svc = service
        self.get_project_id = get_project_id
        self._last_compare_rows: List[Dict] = []
        self._export_helper = ResultExportHelper()
        self._init_result_task_support()
        self._build_ui()

    def refresh_runs(self) -> None:
        self.on_refresh_compare_runs()

    def clear_compare(self) -> None:
        self._last_compare_rows = []
        self.compare_model.removeRows(0, self.compare_model.rowCount())
        self.compare_detail.clear()
        self.lbl_compare_summary.setText("No comparison loaded")

    def reset_view(self) -> None:
        self._cancel_pending_tasks()
        self.compare_run_a.blockSignals(True)
        self.compare_run_b.blockSignals(True)
        self.compare_run_a.clear()
        self.compare_run_b.clear()
        self.compare_run_a.blockSignals(False)
        self.compare_run_b.blockSignals(False)
        self.chk_compare_changes_only.blockSignals(True)
        self.chk_compare_changes_only.setChecked(False)
        self.chk_compare_changes_only.blockSignals(False)
        self.compare_delta_threshold.clear()
        for combo in (
            self.compare_filter_test,
            self.compare_filter_band,
            self.compare_filter_bw,
            self.compare_filter_channel,
            self.compare_filter_screenshot,
        ):
            combo.blockSignals(True)
            combo.clear()
        self.compare_filter_test.addItem("ALL")
        self.compare_filter_band.addItem("ALL")
        self.compare_filter_bw.addItem("ALL")
        self.compare_filter_channel.addItem("ALL")
        self.compare_filter_screenshot.addItems(["ALL", "YES", "NO"])
        for combo in (
            self.compare_filter_test,
            self.compare_filter_band,
            self.compare_filter_bw,
            self.compare_filter_channel,
            self.compare_filter_screenshot,
        ):
            combo.blockSignals(False)
        self.clear_compare()
        self._set_busy(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.compare_run_a = QComboBox()
        self.compare_run_b = QComboBox()
        self.btn_refresh_compare_runs = QPushButton("Refresh Runs")
        self.btn_load_compare = QPushButton("Compare")
        self.chk_compare_changes_only = QCheckBox("Changed only")
        self.lbl_compare_summary = QLabel("No comparison loaded")

        top.addWidget(QLabel("Run A:"))
        top.addWidget(self.compare_run_a, 2)
        top.addSpacing(8)
        top.addWidget(QLabel("Run B:"))
        top.addWidget(self.compare_run_b, 2)
        top.addWidget(self.chk_compare_changes_only)
        top.addWidget(self.btn_refresh_compare_runs)
        top.addWidget(self.btn_load_compare)
        layout.addLayout(top)

        filters = QHBoxLayout()
        self.compare_filter_test = QComboBox()
        self.compare_filter_test.addItem("ALL")
        self.compare_filter_band = QComboBox()
        self.compare_filter_band.addItem("ALL")
        self.compare_filter_bw = QComboBox()
        self.compare_filter_bw.addItem("ALL")
        self.compare_filter_channel = QComboBox()
        self.compare_filter_channel.addItem("ALL")
        self.compare_filter_screenshot = QComboBox()
        self.compare_filter_screenshot.addItems(["ALL", "YES", "NO"])
        self.compare_delta_threshold = QLineEdit()
        self.compare_delta_threshold.setPlaceholderText("Delta threshold")

        filters.addWidget(QLabel("Test:"))
        filters.addWidget(self.compare_filter_test)
        filters.addSpacing(8)
        filters.addWidget(QLabel("Band:"))
        filters.addWidget(self.compare_filter_band)
        filters.addSpacing(8)
        filters.addWidget(QLabel("BW:"))
        filters.addWidget(self.compare_filter_bw)
        filters.addSpacing(8)
        filters.addWidget(QLabel("CH:"))
        filters.addWidget(self.compare_filter_channel)
        filters.addSpacing(8)
        filters.addWidget(QLabel("Shot:"))
        filters.addWidget(self.compare_filter_screenshot)
        filters.addSpacing(8)
        filters.addWidget(QLabel("Min Delta:"))
        filters.addWidget(self.compare_delta_threshold)
        layout.addLayout(filters)

        actions = QHBoxLayout()
        self.btn_export_compare_csv = QPushButton("Export CSV")
        self.btn_export_compare_excel = QPushButton("Export Excel")
        actions.addWidget(self.btn_export_compare_csv)
        actions.addWidget(self.btn_export_compare_excel)
        actions.addStretch(1)
        actions.addWidget(self.lbl_compare_summary)
        layout.addLayout(actions)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Vertical)

        self.compare_table = QTableView()
        self.compare_model = QStandardItemModel()
        self.compare_model.setSortRole(Qt.UserRole)
        self.compare_model.setHorizontalHeaderLabels([
            "Test", "Band", "Standard", "Data Rate", "BW", "CH", "Voltage Cond", "Voltage (V)", "Run A", "Run B", "Delta", "Unit", "Status A", "Status B",
        ])
        self.compare_table.setModel(self.compare_model)
        self.compare_table.setSelectionBehavior(QTableView.SelectRows)
        self.compare_table.setSelectionMode(QTableView.ExtendedSelection)
        self.compare_table.horizontalHeader().setStretchLastSection(True)
        self.compare_table.setSortingEnabled(True)
        self.compare_table.setAlternatingRowColors(True)
        self.compare_table.setStyleSheet(
            "QTableView { alternate-background-color: #141b24; gridline-color: #334155; "
            "selection-background-color: #1d4ed8; selection-color: white; }"
        )
        splitter.addWidget(self.compare_table)

        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(QLabel("Compare Detail"))
        self.compare_detail = QTextEdit()
        self.compare_detail.setReadOnly(True)
        detail_layout.addWidget(self.compare_detail)
        splitter.addWidget(detail_widget)
        splitter.setSizes([700, 250])
        layout.addWidget(splitter, 1)

        self.btn_refresh_compare_runs.clicked.connect(self.on_refresh_compare_runs)
        self.btn_load_compare.clicked.connect(self.on_load_compare)
        self.chk_compare_changes_only.stateChanged.connect(self.on_load_compare)
        self.btn_export_compare_csv.clicked.connect(self.on_export_compare_csv)
        self.btn_export_compare_excel.clicked.connect(self.on_export_compare_excel)
        self.compare_filter_test.currentIndexChanged.connect(self.on_load_compare)
        self.compare_filter_band.currentIndexChanged.connect(self.on_load_compare)
        self.compare_filter_bw.currentIndexChanged.connect(self.on_load_compare)
        self.compare_filter_channel.currentIndexChanged.connect(self.on_load_compare)
        self.compare_filter_screenshot.currentIndexChanged.connect(self.on_load_compare)
        self.compare_delta_threshold.returnPressed.connect(self.on_load_compare)
        self.compare_table.selectionModel().selectionChanged.connect(self.on_compare_selection_changed)

    def _set_busy_impl(self, busy: bool, action: str = "") -> None:
        self.btn_refresh_compare_runs.setEnabled(not busy)
        self.btn_load_compare.setEnabled(not busy)
        self.btn_export_compare_csv.setEnabled(not busy)
        self.btn_export_compare_excel.setEnabled(not busy)
        self.chk_compare_changes_only.setEnabled(not busy)

    def _fill_run_combo(self, combo: QComboBox, runs: List[Dict]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for row in runs:
            run_id = row.get("run_id", "")
            started_at = row.get("started_at", "")
            status = row.get("status", "")
            preset_name = row.get("preset_name", "") or row.get("preset_id", "")
            combo.addItem(f"{started_at} | {status} | {preset_name}", run_id)

        if current:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def on_refresh_compare_runs(self):
        project_id = self.get_project_id()
        if not project_id:
            self.reset_view()
            return
        try:
            runs = self.svc.list_runs_for_results(project_id, limit=100)
        except Exception as e:
            QMessageBox.critical(self, "Load Runs Failed", str(e))
            return

        self._fill_run_combo(self.compare_run_a, runs)
        self._fill_run_combo(self.compare_run_b, runs)
        if self.compare_run_b.count() > 1 and self.compare_run_b.currentIndex() == 0:
            self.compare_run_b.setCurrentIndex(1)

    def _refresh_compare_filter_options(self, rows: List[Dict]) -> None:
        current_test = self.compare_filter_test.currentText()
        current_band = self.compare_filter_band.currentText()
        current_bw = self.compare_filter_bw.currentText()
        current_channel = self.compare_filter_channel.currentText()

        tests = sorted({str(r.get("test_type", "")).strip() for r in rows if r.get("test_type")})
        bands = sorted({str(r.get("band", "")).strip() for r in rows if r.get("band")})
        bws = sorted({int(r.get("bw_mhz")) for r in rows if str(r.get("bw_mhz", "")).strip() != ""})
        channels = sorted({int(r.get("channel")) for r in rows if str(r.get("channel", "")).strip() != ""})

        combos = [self.compare_filter_test, self.compare_filter_band, self.compare_filter_bw, self.compare_filter_channel]
        for combo in combos:
            combo.blockSignals(True)

        self.compare_filter_test.clear()
        self.compare_filter_test.addItem("ALL")
        for value in tests:
            self.compare_filter_test.addItem(value)

        self.compare_filter_band.clear()
        self.compare_filter_band.addItem("ALL")
        for value in bands:
            self.compare_filter_band.addItem(value)

        self.compare_filter_bw.clear()
        self.compare_filter_bw.addItem("ALL")
        for value in bws:
            self.compare_filter_bw.addItem(str(value))

        self.compare_filter_channel.clear()
        self.compare_filter_channel.addItem("ALL")
        for value in channels:
            self.compare_filter_channel.addItem(str(value))

        idx = self.compare_filter_test.findText(current_test)
        self.compare_filter_test.setCurrentIndex(idx if idx >= 0 else 0)
        idx = self.compare_filter_band.findText(current_band)
        self.compare_filter_band.setCurrentIndex(idx if idx >= 0 else 0)
        idx = self.compare_filter_bw.findText(current_bw)
        self.compare_filter_bw.setCurrentIndex(idx if idx >= 0 else 0)
        idx = self.compare_filter_channel.findText(current_channel)
        self.compare_filter_channel.setCurrentIndex(idx if idx >= 0 else 0)

        for combo in combos:
            combo.blockSignals(False)

    def _apply_compare_filters(self, rows: List[Dict]) -> List[Dict]:
        filtered = []
        test_filter = self.compare_filter_test.currentText()
        band_filter = self.compare_filter_band.currentText()
        bw_filter = self.compare_filter_bw.currentText()
        channel_filter = self.compare_filter_channel.currentText()
        screenshot_filter = self.compare_filter_screenshot.currentText()
        threshold_text = self.compare_delta_threshold.text().strip()
        threshold = None
        if threshold_text:
            try:
                threshold = abs(float(threshold_text))
            except Exception:
                threshold = None

        for row in rows:
            if test_filter != "ALL" and str(row.get("test_type", "")) != test_filter:
                continue
            if band_filter != "ALL" and str(row.get("band", "")) != band_filter:
                continue
            if bw_filter != "ALL" and str(row.get("bw_mhz", "")) != bw_filter:
                continue
            if channel_filter != "ALL" and str(row.get("channel", "")) != channel_filter:
                continue

            has_screenshot = bool(row.get("has_screenshot_a") or row.get("has_screenshot_b"))
            if screenshot_filter == "YES" and not has_screenshot:
                continue
            if screenshot_filter == "NO" and has_screenshot:
                continue

            if threshold is not None:
                try:
                    if abs(float(row.get("delta_value", ""))) < threshold:
                        continue
                except Exception:
                    continue
            filtered.append(row)
        return filtered

    def _render_compare_rows(self, rows: List[Dict]) -> None:
        headers = ["Test", "Band", "Standard", "Data Rate", "BW", "CH", "Voltage Cond", "Voltage (V)", "Run A", "Run B", "Delta", "Unit", "Status A", "Status B"]
        self.compare_model.clear()
        self.compare_model.setHorizontalHeaderLabels(headers)

        for row in rows:
            delta_text = format_difference_value(row.get("delta_value"))
            voltage_text = self._format_compare_voltage(row)
            display_values = [
                str(row.get("test_type", "")),
                str(row.get("band", "")),
                str(row.get("standard", "")),
                str(row.get("data_rate", "")),
                str(row.get("bw_mhz", "")),
                str(row.get("channel", "")),
                str(row.get("voltage_condition", "")),
                voltage_text,
                format_numeric_value(row.get("measured_a")),
                format_numeric_value(row.get("measured_b")),
                delta_text,
                str(row.get("unit", "")),
                str(row.get("status_a", "")),
                str(row.get("status_b", "")),
            ]
            sort_values = [
                str(row.get("test_type", "")),
                str(row.get("band", "")),
                str(row.get("standard", "")),
                str(row.get("data_rate", "")),
                self._as_sortable_number(row.get("bw_mhz")),
                self._as_sortable_number(row.get("channel")),
                str(row.get("voltage_condition", "")),
                self._as_sortable_number(row.get("target_voltage_v_a", row.get("target_voltage_v_b"))),
                self._as_sortable_number(row.get("measured_a")),
                self._as_sortable_number(row.get("measured_b")),
                self._as_sortable_number(row.get("delta_value")),
                str(row.get("unit", "")),
                str(row.get("status_a", "")),
                str(row.get("status_b", "")),
            ]
            items = []
            for idx, text in enumerate(display_values):
                item = QStandardItem(text)
                item.setData(sort_values[idx], Qt.UserRole)
                if idx in (4, 5, 6, 7, 8, 9, 10, 11):
                    item.setTextAlignment(Qt.AlignCenter)
                items.append(item)

            status_a = str(row.get("status_a", ""))
            status_b = str(row.get("status_b", ""))
            delta = row.get("delta_value", "")
            changed = bool(row.get("changed"))

            row_color = None
            text_color = None
            font = QFont()
            if status_a == "PASS" and status_b == "FAIL":
                row_color = QColor(123, 31, 31)
                text_color = QColor(255, 245, 245)
                font.setBold(True)
            elif status_a == "FAIL" and status_b == "PASS":
                row_color = QColor(27, 94, 32)
                text_color = QColor(245, 255, 245)
                font.setBold(True)
            elif changed:
                try:
                    if abs(float(delta)) > 0:
                        row_color = QColor(120, 53, 15)
                        text_color = QColor(255, 251, 235)
                    else:
                        row_color = QColor(55, 65, 81)
                        text_color = QColor(248, 250, 252)
                except Exception:
                    row_color = QColor(55, 65, 81)
                    text_color = QColor(248, 250, 252)

            if row_color is not None:
                for item in items:
                    item.setBackground(row_color)
                    if text_color is not None:
                        item.setForeground(QBrush(text_color))
                    item.setFont(font)

            self.compare_model.appendRow(items)

        self.compare_table.resizeColumnsToContents()

    def on_load_compare(self):
        project_id = self.get_project_id()
        if not project_id:
            return

        run_a = self.compare_run_a.currentData()
        run_b = self.compare_run_b.currentData()
        if not run_a or not run_b:
            return
        if run_a == run_b:
            self.lbl_compare_summary.setText("Select two different runs.")
            self.compare_model.removeRows(0, self.compare_model.rowCount())
            return

        changed_only = self.chk_compare_changes_only.isChecked()

        def _task():
            rows = self.svc.get_comparable_results(project_id, run_a, run_b)
            rows_a = self.svc.get_results_page(project_id=project_id, run_id=run_a, status_filter="ALL", offset=0, limit=5000)
            rows_b = self.svc.get_results_page(project_id=project_id, run_id=run_b, status_filter="ALL", offset=0, limit=5000)
            rows = self._enrich_compare_rows(rows, rows_a, rows_b)
            if changed_only:
                rows = [r for r in rows if r.get("changed")]
            return {
                "project_id": project_id,
                "run_a": run_a,
                "run_b": run_b,
                "changed_only": changed_only,
                "rows": rows,
            }

        def _apply(payload: Dict) -> None:
            if payload.get("project_id") != self.get_project_id():
                return
            if payload.get("run_a") != self.compare_run_a.currentData():
                return
            if payload.get("run_b") != self.compare_run_b.currentData():
                return
            if bool(payload.get("changed_only")) != self.chk_compare_changes_only.isChecked():
                return
            rows = list(payload.get("rows") or [])
            self._last_compare_rows = rows
            self._refresh_compare_filter_options(rows)
            filtered = self._apply_compare_filters(rows)
            changed_count = sum(1 for r in filtered if r.get("changed"))
            self.lbl_compare_summary.setText(f"Rows {len(filtered)} | Changed {changed_count}")
            self._render_compare_rows(filtered)
            if filtered:
                self.compare_table.selectRow(0)
            else:
                self.compare_detail.clear()

        self._start_task(
            action="load_compare",
            task=_task,
            on_success=_apply,
            error_title="Compare Failed",
            log_prefix="compare task",
        )

    def on_compare_selection_changed(self, selected, deselected):
        sel = self.compare_table.selectionModel().selectedRows()
        if not sel:
            self.compare_detail.clear()
            return
        row = self._filtered_compare_row(sel[0].row())
        if not row:
            self.compare_detail.clear()
            return
        self.compare_detail.setPlainText(self._build_compare_detail_text(row))

    def _filtered_compare_row(self, row_index: int) -> Dict | None:
        rows = self._apply_compare_filters(self._last_compare_rows)
        if 0 <= row_index < len(rows):
            return rows[row_index]
        return None

    def _build_compare_detail_text(self, row: Dict) -> str:
        lines = [
            f"Test: {row.get('test_type', '')}",
            f"Band/Standard/Data Rate/BW/CH: {row.get('band', '')} / {row.get('standard', '')} / {row.get('data_rate', '')} / {row.get('bw_mhz', '')} / {row.get('channel', '')}",
            f"Corrected A: {format_numeric_value(row.get('corrected_measured_a', row.get('measured_a')))}",
            f"Corrected B: {format_numeric_value(row.get('corrected_measured_b', row.get('measured_b')))}",
            f"Raw A: {format_numeric_value(row.get('raw_measured_a'))}",
            f"Raw B: {format_numeric_value(row.get('raw_measured_b'))}",
            f"Applied Correction A (dB): {format_numeric_value(row.get('applied_correction_db_a'))}",
            f"Applied Correction B (dB): {format_numeric_value(row.get('applied_correction_db_b'))}",
            f"Correction Delta (B-A): {format_difference_value(row.get('delta_applied_correction_db'))}",
            f"Delta: {format_difference_value(row.get('delta_value'))}",
            f"Unit: {row.get('unit', '')}",
            f"Status A/B: {row.get('status_a', '')} / {row.get('status_b', '')}",
            f"Voltage Condition: {row.get('voltage_condition', '')}",
            f"Nominal Voltage A/B: {row.get('nominal_voltage_v_a', '')} / {row.get('nominal_voltage_v_b', '')}",
            f"Target Voltage A/B: {row.get('target_voltage_v_a', '')} / {row.get('target_voltage_v_b', '')}",
            f"Difference A: {format_difference(row.get('difference_a'), row.get('difference_unit', ''))}",
            f"Difference B: {format_difference(row.get('difference_b'), row.get('difference_unit', ''))}",
            f"Limit A/B: {row.get('limit_a', '')} / {row.get('limit_b', '')}",
            f"Comparator A/B: {row.get('comparator_a', '')} / {row.get('comparator_b', '')}",
            f"Correction Profile A/B: {row.get('correction_profile_name_a', '')} / {row.get('correction_profile_name_b', '')}",
            f"Correction Mode A/B: {row.get('correction_mode_a', '')} / {row.get('correction_mode_b', '')}",
            f"Correction Path A/B: {row.get('correction_bound_path_a', '')} / {row.get('correction_bound_path_b', '')}",
            "Breakdown A:",
            self._format_correction_breakdown(row.get("correction_breakdown_a") or {}, row.get("applied_correction_db_a")),
            "Breakdown B:",
            self._format_correction_breakdown(row.get("correction_breakdown_b") or {}, row.get("applied_correction_db_b")),
            f"Screenshot A: {row.get('screenshot_path_a', '') or row.get('screenshot_abs_path_a', '') or '(none)'}",
            f"Screenshot B: {row.get('screenshot_path_b', '') or row.get('screenshot_abs_path_b', '') or '(none)'}",
        ]
        return "\n".join(lines)

    def _fetch_compare_rows_for_export(self) -> List[Dict]:
        if not self._last_compare_rows:
            raise ValueError("No compare rows loaded")
        return self._apply_compare_filters(list(self._last_compare_rows))

    def on_export_compare_csv(self):
        try:
            rows = self._fetch_compare_rows_for_export()
        except Exception as e:
            QMessageBox.critical(self, "Export Compare CSV Failed", str(e))
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export Compare (CSV)", "compare_results.csv", "CSV (*.csv)")
        if not path:
            return

        def _task():
            self._export_helper.write_compare_csv(path, rows)
            return {"path": path}

        def _done(payload: Dict) -> None:
            QMessageBox.information(self, "Export Compare CSV", f"Saved:\n{payload.get('path', path)}")

        self._start_task(
            action="export_compare_csv",
            task=_task,
            on_success=_done,
            error_title="Export Compare CSV Failed",
            log_prefix="compare task",
        )

    def on_export_compare_excel(self):
        try:
            rows = self._fetch_compare_rows_for_export()
        except Exception as e:
            QMessageBox.critical(self, "Export Compare Excel Failed", str(e))
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export Compare (Excel)", "compare_results.xlsx", "Excel (*.xlsx)")
        if not path:
            return

        def _task():
            self._export_helper.write_compare_excel(path, rows)
            return {"path": path}

        def _done(payload: Dict) -> None:
            QMessageBox.information(self, "Export Compare Excel", f"Saved:\n{payload.get('path', path)}")

        self._start_task(
            action="export_compare_excel",
            task=_task,
            on_success=_done,
            error_title="Export Compare Excel Failed",
            log_prefix="compare task",
        )

    def _enrich_compare_rows(self, compare_rows: List[Dict], rows_a: List[Dict], rows_b: List[Dict]) -> List[Dict]:
        map_a = {self._result_identity_key(row): dict(row or {}) for row in rows_a}
        map_b = {self._result_identity_key(row): dict(row or {}) for row in rows_b}
        out = []
        for row in compare_rows:
            compare_row = dict(row or {})
            key = self._compare_identity_key(compare_row)
            a = map_a.get(key, {})
            b = map_b.get(key, {})
            compare_row["corrected_measured_a"] = a.get("measured_value", compare_row.get("measured_a", ""))
            compare_row["corrected_measured_b"] = b.get("measured_value", compare_row.get("measured_b", ""))
            compare_row["raw_measured_a"] = a.get("raw_measured_value", "")
            compare_row["raw_measured_b"] = b.get("raw_measured_value", "")
            compare_row["applied_correction_db_a"] = a.get("applied_correction_db", "")
            compare_row["applied_correction_db_b"] = b.get("applied_correction_db", "")
            compare_row["correction_mode_a"] = str(a.get("correction_mode", "") or "")
            compare_row["correction_mode_b"] = str(b.get("correction_mode", "") or "")
            compare_row["correction_applied_a"] = bool(a.get("correction_applied"))
            compare_row["correction_applied_b"] = bool(b.get("correction_applied"))
            compare_row["correction_breakdown_a"] = dict(a.get("correction_breakdown") or {})
            compare_row["correction_breakdown_b"] = dict(b.get("correction_breakdown") or {})
            compare_row["correction_breakdown_text_a"] = self._format_correction_breakdown(
                compare_row.get("correction_breakdown_a") or {},
                compare_row.get("applied_correction_db_a"),
            )
            compare_row["correction_breakdown_text_b"] = self._format_correction_breakdown(
                compare_row.get("correction_breakdown_b") or {},
                compare_row.get("applied_correction_db_b"),
            )
            compare_row["delta_applied_correction_db"] = self._safe_delta(
                compare_row.get("applied_correction_db_b"),
                compare_row.get("applied_correction_db_a"),
            )
            out.append(compare_row)
        return out

    def _result_identity_key(self, row: Dict) -> tuple:
        return (
            str(row.get("test_key", "") or ""),
            str(row.get("test_type", "") or ""),
            str(row.get("band", "") or ""),
            str(row.get("standard", "") or ""),
            str(row.get("channel", "") or ""),
            str(row.get("bw_mhz", "") or ""),
            str(row.get("data_rate", "") or ""),
            str(row.get("voltage_condition", "") or ""),
            str(row.get("target_voltage_v", "") or ""),
        )

    def _compare_identity_key(self, row: Dict) -> tuple:
        target_voltage = row.get("target_voltage_v_a")
        if target_voltage in (None, ""):
            target_voltage = row.get("target_voltage_v_b")
        return (
            str(row.get("test_key", "") or ""),
            str(row.get("test_type", "") or ""),
            str(row.get("band", "") or ""),
            str(row.get("standard", "") or ""),
            str(row.get("channel", "") or ""),
            str(row.get("bw_mhz", "") or ""),
            str(row.get("data_rate", "") or ""),
            str(row.get("voltage_condition", "") or ""),
            str(target_voltage or ""),
        )

    def _format_correction_breakdown(self, breakdown: Dict, applied_total) -> str:
        payload = dict(breakdown or {})
        if not payload:
            if applied_total in (None, "", 0, 0.0):
                return "(none)"
            return f"  total_db={format_numeric_value(applied_total)}"

        ordered_keys = [
            "cable_loss_db",
            "attenuator_db",
            "dut_cable_loss_db",
            "switchbox_loss_db",
            "divider_loss_db",
            "external_gain_db",
            "manual_offset_db",
        ]
        lines = []
        for key in ordered_keys:
            if key not in payload:
                continue
            lines.append(f"  {key}={format_numeric_value(payload.get(key))}")
        lines.append(f"  total_db={format_numeric_value(applied_total)}")
        return "\n".join(lines)

    def _safe_delta(self, right, left):
        try:
            if right in (None, "") or left in (None, ""):
                return ""
            return round(float(right) - float(left), 3)
        except Exception:
            return ""

    def _as_sortable_number(self, value) -> float:
        try:
            if value in (None, ""):
                return float("-inf")
            return float(value)
        except Exception:
            return float("-inf")

    def _format_compare_voltage(self, row: Dict) -> str:
        preferred = row.get("target_voltage_v_a")
        fallback = row.get("target_voltage_v_b")
        value = preferred if preferred not in (None, "") else fallback
        try:
            if value in (None, ""):
                return ""
            return f"{float(value):g}"
        except Exception:
            return str(value or "")
