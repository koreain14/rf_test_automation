from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.device_models import EquipmentProfile


class EquipmentProfileTab(QWidget):
    def __init__(self, profile_repo, device_registry, parent=None):
        super().__init__(parent)
        self.profile_repo = profile_repo
        self.device_registry = device_registry
        self._build_ui()
        self.reload_all()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_reload = QPushButton("Reload")
        self.btn_delete = QPushButton("Delete")
        top.addWidget(self.btn_reload)
        top.addWidget(self.btn_delete)
        top.addStretch(1)
        layout.addLayout(top)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Name", "Analyzer", "Turntable", "Mast", "SwitchBox", "Power"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        self.name_edit = QLineEdit()
        self.analyzer_combo = QComboBox()
        self.turntable_combo = QComboBox()
        self.mast_combo = QComboBox()
        self.switchbox_combo = QComboBox()
        self.power_combo = QComboBox()

        form.addRow("Profile Name", self.name_edit)
        form.addRow("Analyzer", self.analyzer_combo)
        form.addRow("Turntable", self.turntable_combo)
        form.addRow("Mast", self.mast_combo)
        form.addRow("SwitchBox", self.switchbox_combo)
        form.addRow("Power Supply", self.power_combo)

        btns = QHBoxLayout()
        self.btn_new = QPushButton("New")
        self.btn_save = QPushButton("Save")
        btns.addWidget(self.btn_new)
        btns.addWidget(self.btn_save)
        form.addRow(btns)

        layout.addWidget(form_widget)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.btn_reload.clicked.connect(self.reload_all)
        self.btn_new.clicked.connect(self.on_new)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_delete.clicked.connect(self.on_delete)

    def _fill_device_combo(self, combo: QComboBox, device_type: str, selected: str | None = None) -> None:
        combo.clear()
        combo.addItem("(None)", None)
        for d in self.device_registry.list_devices_by_type(device_type):
            combo.addItem(d.name, d.name)
        if selected:
            idx = combo.findData(selected)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _load_profile_to_form(self, profile: EquipmentProfile | None) -> None:
        self._fill_device_combo(self.analyzer_combo, "analyzer", profile.analyzer if profile else None)
        self._fill_device_combo(self.turntable_combo, "turntable", profile.turntable if profile else None)
        self._fill_device_combo(self.mast_combo, "mast", profile.mast if profile else None)
        self._fill_device_combo(self.switchbox_combo, "switchbox", profile.switchbox if profile else None)
        self._fill_device_combo(self.power_combo, "power_supply", profile.power_supply if profile else None)

        self.name_edit.setText(profile.name if profile else "")

    def reload_all(self) -> None:
        profiles = self.profile_repo.list_profiles()
        self.table.setRowCount(len(profiles))
        for row, p in enumerate(profiles):
            self.table.setItem(row, 0, QTableWidgetItem(p.name))
            self.table.setItem(row, 1, QTableWidgetItem(p.analyzer or ""))
            self.table.setItem(row, 2, QTableWidgetItem(p.turntable or ""))
            self.table.setItem(row, 3, QTableWidgetItem(p.mast or ""))
            self.table.setItem(row, 4, QTableWidgetItem(p.switchbox or ""))
            self.table.setItem(row, 5, QTableWidgetItem(p.power_supply or ""))
        self._load_profile_to_form(None)
        self.status_label.setText(f"{len(profiles)} profile(s) loaded")

    def selected_profile_name(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text().strip() if item else None

    def on_table_selection_changed(self) -> None:
        name = self.selected_profile_name()
        profile = self.profile_repo.get_profile(name) if name else None
        self._load_profile_to_form(profile)

    def on_new(self) -> None:
        self._load_profile_to_form(None)

    def on_save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Save failed", "Profile name is required")
            return

        profile = EquipmentProfile(
            name=name,
            analyzer=self.analyzer_combo.currentData(),
            turntable=self.turntable_combo.currentData(),
            mast=self.mast_combo.currentData(),
            switchbox=self.switchbox_combo.currentData(),
            power_supply=self.power_combo.currentData(),
        )
        self.profile_repo.upsert_profile(profile)
        self.reload_all()
        self.status_label.setText(f"Saved: {name}")

    def on_delete(self) -> None:
        name = self.selected_profile_name()
        if not name:
            QMessageBox.information(self, "Delete", "Select a profile first.")
            return
        self.profile_repo.remove_profile(name)
        self.reload_all()
        self.status_label.setText(f"Deleted: {name}")
