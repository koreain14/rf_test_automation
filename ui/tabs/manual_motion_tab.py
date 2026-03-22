from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class ManualMotionTab(QWidget):
    def __init__(self, instrument_manager, get_equipment_profile_name, store_path: Path, parent=None):
        super().__init__(parent)
        self.instrument_manager = instrument_manager
        self.get_equipment_profile_name = get_equipment_profile_name
        self.store_path = store_path
        self._session = None
        self._saved_positions = {}
        self._build_ui()
        self._load_saved_positions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_connect = QPushButton("Connect Motion")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_read = QPushButton("Read Position")
        top.addWidget(self.btn_connect)
        top.addWidget(self.btn_disconnect)
        top.addWidget(self.btn_read)
        top.addStretch(1)
        layout.addLayout(top)

        grid = QGridLayout()

        self.turntable_spin = QDoubleSpinBox()
        self.turntable_spin.setRange(-360.0, 360.0)
        self.turntable_spin.setDecimals(1)
        self.turntable_spin.setSuffix(" deg")
        self.btn_move_turntable = QPushButton("Move Turntable")

        self.mast_spin = QDoubleSpinBox()
        self.mast_spin.setRange(0.0, 1000.0)
        self.mast_spin.setDecimals(1)
        self.mast_spin.setSuffix(" cm")
        self.btn_move_mast = QPushButton("Move Mast")

        self.polarization_combo = QComboBox()
        self.polarization_combo.addItems(["Horizontal", "Vertical"])
        self.btn_set_polarization = QPushButton("Set Polarization")

        self.btn_apply_all = QPushButton("Apply All")

        grid.addWidget(QLabel("Turntable Angle"), 0, 0)
        grid.addWidget(self.turntable_spin, 0, 1)
        grid.addWidget(self.btn_move_turntable, 0, 2)

        grid.addWidget(QLabel("Mast Height"), 1, 0)
        grid.addWidget(self.mast_spin, 1, 1)
        grid.addWidget(self.btn_move_mast, 1, 2)

        grid.addWidget(QLabel("Mast Polarization"), 2, 0)
        grid.addWidget(self.polarization_combo, 2, 1)
        grid.addWidget(self.btn_set_polarization, 2, 2)

        grid.addWidget(self.btn_apply_all, 3, 2)
        layout.addLayout(grid)

        save_row = QHBoxLayout()
        self.saved_combo = QComboBox()
        self.saved_combo.setEditable(True)
        self.btn_refresh_saved = QPushButton("Refresh Saved")
        self.btn_save_position = QPushButton("Save Position")
        self.btn_load_position = QPushButton("Load Saved")
        self.btn_delete_position = QPushButton("Delete Saved")
        save_row.addWidget(QLabel("Saved Positions"))
        save_row.addWidget(self.saved_combo, 2)
        save_row.addWidget(self.btn_refresh_saved)
        save_row.addWidget(self.btn_save_position)
        save_row.addWidget(self.btn_load_position)
        save_row.addWidget(self.btn_delete_position)
        layout.addLayout(save_row)

        self.output_box = QPlainTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMinimumHeight(180)
        layout.addWidget(self.output_box)

        self.btn_connect.clicked.connect(self.on_connect)
        self.btn_disconnect.clicked.connect(self.on_disconnect)
        self.btn_read.clicked.connect(self.on_read_position)
        self.btn_move_turntable.clicked.connect(self.on_move_turntable)
        self.btn_move_mast.clicked.connect(self.on_move_mast)
        self.btn_set_polarization.clicked.connect(self.on_set_polarization)
        self.btn_apply_all.clicked.connect(self.on_apply_all)
        self.btn_refresh_saved.clicked.connect(self._load_saved_positions)
        self.btn_save_position.clicked.connect(self.on_save_position)
        self.btn_load_position.clicked.connect(self.on_load_position)
        self.btn_delete_position.clicked.connect(self.on_delete_position)

    def _append_log(self, text: str) -> None:
        current = self.output_box.toPlainText().strip()
        self.output_box.setPlainText((current + "\n" + text).strip())

    def _load_saved_positions(self) -> None:
        if self.store_path.exists():
            try:
                self._saved_positions = json.loads(self.store_path.read_text(encoding="utf-8"))
                if not isinstance(self._saved_positions, dict):
                    self._saved_positions = {}
            except Exception:
                self._saved_positions = {}
        else:
            self._saved_positions = {}

        current = self.saved_combo.currentText()
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        for name in sorted(self._saved_positions.keys()):
            self.saved_combo.addItem(name)
        self.saved_combo.setEditText(current)
        self.saved_combo.blockSignals(False)

    def _save_positions_file(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(self._saved_positions, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_session(self):
        if self._session is not None:
            return self._session
        profile_name = self.get_equipment_profile_name()
        if not profile_name:
            raise RuntimeError("Select an equipment profile first.")
        self._session = self.instrument_manager.create_motion_session(profile_name)
        return self._session

    def on_connect(self) -> None:
        try:
            session = self._ensure_session()
            tt = getattr(session, "turntable", None)
            mast = getattr(session, "mast", None)
            self._append_log(
                f"Motion session ready | turntable={'OK' if tt else 'None'} | mast={'OK' if mast else 'None'}"
            )
        except Exception as e:
            QMessageBox.warning(self, "Connect Motion", str(e))
            self._append_log(f"Connect failed: {e}")

    def on_disconnect(self) -> None:
        if self._session is not None:
            for attr in ("turntable", "mast"):
                dev = getattr(self._session, attr, None)
                if dev is not None and hasattr(dev, "disconnect"):
                    try:
                        dev.disconnect()
                    except Exception:
                        log.warning("disconnect failed: %s", attr, exc_info=True)
            self._session = None
        self._append_log("Motion session disconnected.")

    def on_read_position(self) -> None:
        try:
            session = self._ensure_session()
            turntable = getattr(session, "turntable", None)
            mast = getattr(session, "mast", None)

            if turntable is not None and hasattr(turntable, "get_position"):
                angle = float(turntable.get_position())
                self.turntable_spin.setValue(angle)
                self._append_log(f"Turntable position read: {angle} deg")
            else:
                self._append_log("Turntable read skipped: not configured.")

            if mast is not None and hasattr(mast, "get_position"):
                height = float(mast.get_position())
                self.mast_spin.setValue(height)
                self._append_log(f"Mast position read: {height} cm")
            else:
                self._append_log("Mast read skipped: not configured.")

            if mast is not None and hasattr(mast, "get_polarization"):
                pol = str(mast.get_polarization())
                idx = self.polarization_combo.findText(pol)
                if idx >= 0:
                    self.polarization_combo.setCurrentIndex(idx)
                self._append_log(f"Mast polarization read: {pol}")
            else:
                self._append_log("Polarization read skipped: not supported.")
        except Exception as e:
            QMessageBox.warning(self, "Read Position", str(e))
            self._append_log(f"Read failed: {e}")

    def _move_turntable(self) -> str:
        session = self._ensure_session()
        turntable = getattr(session, "turntable", None)
        if turntable is None or not hasattr(turntable, "move_to"):
            raise RuntimeError("Turntable is not configured in the selected equipment profile.")
        angle = float(self.turntable_spin.value())
        turntable.move_to(angle)
        self._append_log(f"Turntable moved to {angle} deg")
        return f"Turntable={angle} deg"

    def _move_mast(self) -> str:
        session = self._ensure_session()
        mast = getattr(session, "mast", None)
        if mast is None or not hasattr(mast, "move_to"):
            raise RuntimeError("Mast is not configured in the selected equipment profile.")
        height = float(self.mast_spin.value())
        mast.move_to(height)
        self._append_log(f"Mast moved to {height} cm")
        return f"Mast={height} cm"

    def _set_polarization(self) -> str:
        session = self._ensure_session()
        mast = getattr(session, "mast", None)
        if mast is None or not hasattr(mast, "set_polarization"):
            raise RuntimeError("Mast polarization control is not available for the selected profile.")
        pol = self.polarization_combo.currentText()
        mast.set_polarization(pol)
        self._append_log(f"Mast polarization set to {pol}")
        return f"Polarization={pol}"

    def on_move_turntable(self) -> None:
        try:
            self._move_turntable()
        except Exception as e:
            QMessageBox.warning(self, "Move Turntable", str(e))
            self._append_log(f"Turntable move failed: {e}")

    def on_move_mast(self) -> None:
        try:
            self._move_mast()
        except Exception as e:
            QMessageBox.warning(self, "Move Mast", str(e))
            self._append_log(f"Mast move failed: {e}")

    def on_set_polarization(self) -> None:
        try:
            self._set_polarization()
        except Exception as e:
            QMessageBox.warning(self, "Set Polarization", str(e))
            self._append_log(f"Polarization set failed: {e}")

    def on_apply_all(self) -> None:
        actions = [
            ("Turntable", self._move_turntable),
            ("Mast", self._move_mast),
            ("Polarization", self._set_polarization),
        ]
        success = []
        failed = []

        for name, action in actions:
            try:
                success.append(action())
            except Exception as e:
                failed.append(f"{name}: {e}")
                self._append_log(f"{name} apply failed: {e}")

        if failed:
            QMessageBox.warning(
                self,
                "Apply All",
                "Some motion actions failed.\n\n" + "\n".join(failed),
            )
        else:
            self._append_log("Apply all completed: " + ", ".join(success))

    def on_save_position(self) -> None:
        name = self.saved_combo.currentText().strip()
        if not name:
            name = f"POS_{len(self._saved_positions) + 1:02d}"
        self._saved_positions[name] = {
            "turntable_angle_deg": float(self.turntable_spin.value()),
            "mast_height_cm": float(self.mast_spin.value()),
            "mast_polarization": self.polarization_combo.currentText(),
        }
        self._save_positions_file()
        self._load_saved_positions()
        self.saved_combo.setEditText(name)
        self._append_log(f"Saved position: {name}")

    def on_load_position(self) -> None:
        name = self.saved_combo.currentText().strip()
        if not name or name not in self._saved_positions:
            QMessageBox.information(self, "Load Saved", "Select a saved position first.")
            return
        pos = self._saved_positions[name]
        self.turntable_spin.setValue(float(pos.get("turntable_angle_deg", 0.0) or 0.0))
        self.mast_spin.setValue(float(pos.get("mast_height_cm", 0.0) or 0.0))
        pol = str(pos.get("mast_polarization", "Horizontal"))
        idx = self.polarization_combo.findText(pol)
        if idx >= 0:
            self.polarization_combo.setCurrentIndex(idx)
        self._append_log(f"Loaded saved position: {name}")

    def on_delete_position(self) -> None:
        name = self.saved_combo.currentText().strip()
        if not name or name not in self._saved_positions:
            return
        del self._saved_positions[name]
        self._save_positions_file()
        self._load_saved_positions()
        self._append_log(f"Deleted saved position: {name}")
