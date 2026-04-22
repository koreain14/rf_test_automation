from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class DutChannelMonitorDialog(QDialog):
    def __init__(
        self,
        *,
        payload: dict,
        instructions_text: str,
        window_title: str = "",
        start_monitor_callback: Callable[[dict], dict],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.payload = dict(payload or {})
        self.instructions_text = str(instructions_text or "")
        self.window_title = str(window_title or "")
        self.start_monitor_callback = start_monitor_callback
        self._monitor_started = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle(self.window_title or "DUT Channel Setup Monitor")
        self.resize(640, 500)

        layout = QVBoxLayout(self)

        self.instructions_box = QTextEdit()
        self.instructions_box.setReadOnly(True)
        self.instructions_box.setPlainText(self.instructions_text)
        layout.addWidget(self.instructions_box, 1)

        monitor_box = QGroupBox("Analyzer Monitor Preview")
        form = QFormLayout(monitor_box)

        self.lbl_channel = QLabel(str(self._current_value("channel") or self.payload.get("case_key") or "-"))
        self.lbl_frequency = QLabel(self._format_mhz(self._current_value("center_freq_mhz")))
        self.lbl_bandwidth = QLabel(self._format_bw(self._current_value("bw_mhz")))
        self.lbl_standard = QLabel(str(self._current_value("standard") or self.payload.get("standard") or "-"))
        self.lbl_data_rate = QLabel(str(self._current_value("data_rate") or self.payload.get("requested_data_rate") or "-"))
        self.lbl_mode = QLabel(str(self._current_value("phy_mode") or self.payload.get("standard") or "-"))
        self.lbl_voltage_condition = QLabel(str(self._current_value("voltage_condition") or "-"))
        self.lbl_target_voltage = QLabel(self._format_voltage(self._current_value("target_voltage_v")))
        self.lbl_nominal_voltage = QLabel(self._format_voltage(self._current_value("nominal_voltage_v")))
        self.lbl_monitor_status = QLabel("Preparing monitor preview...")
        self.lbl_monitor_source = QLabel("-")
        self.lbl_monitor_span = QLabel("-")
        self.lbl_monitor_message = QLabel("Dialog opened. Monitor preview will start automatically.")
        self.lbl_monitor_message.setWordWrap(True)

        form.addRow("Channel", self.lbl_channel)
        form.addRow("Center Frequency", self.lbl_frequency)
        form.addRow("Bandwidth", self.lbl_bandwidth)
        form.addRow("Standard", self.lbl_standard)
        form.addRow("Data Rate", self.lbl_data_rate)
        form.addRow("Mode", self.lbl_mode)
        form.addRow("Voltage Condition", self.lbl_voltage_condition)
        form.addRow("Target Voltage", self.lbl_target_voltage)
        form.addRow("Nominal Voltage", self.lbl_nominal_voltage)
        form.addRow("Monitor Status", self.lbl_monitor_status)
        form.addRow("Analyzer Source", self.lbl_monitor_source)
        form.addRow("Preview Span", self.lbl_monitor_span)
        form.addRow("Monitor Note", self.lbl_monitor_message)

        layout.addWidget(monitor_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Continue")
        buttons.button(QDialogButtonBox.Cancel).setText("Abort")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._monitor_started:
            self._monitor_started = True
            QTimer.singleShot(0, self._start_monitor_after_show)

    def _start_monitor_after_show(self) -> None:
        result = dict(self.start_monitor_callback(self.payload) or {})
        self.lbl_monitor_status.setText(str(result.get("status") or "UNAVAILABLE"))
        self.lbl_monitor_source.setText(str(result.get("source") or "-"))
        self.lbl_monitor_span.setText(self._format_span(result.get("span_mhz")))
        self.lbl_monitor_message.setText(str(result.get("message") or "Monitor preview finished."))

    def _current_value(self, key: str):
        current = dict(self.payload.get("current") or {})
        return current.get(key)

    def _format_mhz(self, value) -> str:
        try:
            return f"{float(value):.3f} MHz"
        except Exception:
            return "-"

    def _format_bw(self, value) -> str:
        try:
            return f"{float(value):.1f} MHz"
        except Exception:
            return "-"

    def _format_span(self, value) -> str:
        try:
            return f"{float(value):.3f} MHz"
        except Exception:
            return "-"

    def _format_voltage(self, value) -> str:
        try:
            if value in (None, ""):
                return "-"
            return f"{float(value):g} V"
        except Exception:
            return "-"
