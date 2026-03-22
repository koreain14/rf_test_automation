from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout


class RFPathDialog(QDialog):
    def __init__(
        self,
        path_names: list[str],
        antenna_names: list[str] | None = None,
        current_path: str | None = None,
        current_antenna: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("RF Path Settings")
        self.resize(360, 180)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.path_combo = QComboBox()
        self.path_combo.addItem("(None)", None)
        for p in path_names:
            self.path_combo.addItem(p, p)

        if current_path:
            idx = self.path_combo.findData(current_path)
            if idx >= 0:
                self.path_combo.setCurrentIndex(idx)

        self.antenna_combo = QComboBox()
        self.antenna_combo.addItem("(None)", None)
        for ant in (antenna_names or []):
            self.antenna_combo.addItem(ant, ant)

        if current_antenna:
            idx = self.antenna_combo.findData(current_antenna)
            if idx >= 0:
                self.antenna_combo.setCurrentIndex(idx)

        form.addRow(QLabel("Switch Path"), self.path_combo)
        form.addRow(QLabel("Antenna"), self.antenna_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_path(self) -> str | None:
        value = self.path_combo.currentData()
        return str(value) if value else None

    def selected_antenna(self) -> str | None:
        value = self.antenna_combo.currentData()
        return str(value) if value else None
