from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QVBoxLayout,
)


class PowerSettingsDialog(QDialog):
    def __init__(self, initial: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Power Settings")
        self.resize(360, 180)

        initial = dict(initial or {})
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.enable_check = QCheckBox("Enable PSU control for this plan")
        self.enable_check.setChecked(bool(initial.get("enabled", False)))

        self.output_on_check = QCheckBox("Turn output ON at run start")
        self.output_on_check.setChecked(bool(initial.get("output_on", False)))

        self.voltage_spin = QDoubleSpinBox()
        self.voltage_spin.setRange(0.0, 100.0)
        self.voltage_spin.setDecimals(3)
        self.voltage_spin.setValue(float(initial.get("voltage", 0.0) or 0.0))
        self.voltage_spin.setSuffix(" V")

        self.current_spin = QDoubleSpinBox()
        self.current_spin.setRange(0.0, 20.0)
        self.current_spin.setDecimals(3)
        self.current_spin.setValue(float(initial.get("current_limit", 0.0) or 0.0))
        self.current_spin.setSuffix(" A")

        form.addRow(self.enable_check)
        form.addRow(self.output_on_check)
        form.addRow("Voltage", self.voltage_spin)
        form.addRow("Current Limit", self.current_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self) -> dict:
        return {
            "enabled": self.enable_check.isChecked(),
            "output_on": self.output_on_check.isChecked(),
            "voltage": float(self.voltage_spin.value()),
            "current_limit": float(self.current_spin.value()),
        }
