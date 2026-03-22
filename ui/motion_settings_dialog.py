from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QVBoxLayout,
)


class MotionSettingsDialog(QDialog):
    def __init__(self, initial: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Motion Settings")
        self.resize(360, 180)

        initial = dict(initial or {})
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.enable_check = QCheckBox("Enable motion control for this plan")
        self.enable_check.setChecked(bool(initial.get("enabled", False)))

        self.turntable_spin = QDoubleSpinBox()
        self.turntable_spin.setRange(-360.0, 360.0)
        self.turntable_spin.setDecimals(1)
        self.turntable_spin.setValue(float(initial.get("turntable_angle_deg", 0.0) or 0.0))
        self.turntable_spin.setSuffix(" deg")

        self.mast_spin = QDoubleSpinBox()
        self.mast_spin.setRange(0.0, 1000.0)
        self.mast_spin.setDecimals(1)
        self.mast_spin.setValue(float(initial.get("mast_height_cm", 0.0) or 0.0))
        self.mast_spin.setSuffix(" cm")

        form.addRow(self.enable_check)
        form.addRow("Turntable Angle", self.turntable_spin)
        form.addRow("Mast Height", self.mast_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self) -> dict:
        return {
            "enabled": self.enable_check.isChecked(),
            "turntable_angle_deg": float(self.turntable_spin.value()),
            "mast_height_cm": float(self.mast_spin.value()),
        }
