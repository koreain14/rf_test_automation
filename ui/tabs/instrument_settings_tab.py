from __future__ import annotations

from typing import Callable, Dict

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from application.instrument_factory import AutoInstrumentFactory, DummyInstrumentFactory, ScpiInstrumentFactory


class InstrumentSettingsTab(QWidget):
    def __init__(
        self,
        initial_settings: Dict,
        save_settings_callback: Callable[[Dict], None],
        apply_factory_callback: Callable[[object], None],
        parent=None,
    ):
        super().__init__(parent)
        self.save_settings_callback = save_settings_callback
        self.apply_factory_callback = apply_factory_callback
        self._build_ui()
        self.set_settings(initial_settings or {})

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        box = QGroupBox("Measurement Instrument")
        form = QFormLayout(box)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["AUTO", "DUMMY", "SCPI"])

        self.resource_edit = QLineEdit()
        self.resource_edit.setPlaceholderText('e.g. TCPIP0::192.168.0.50::inst0::INSTR')

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(100, 120000)
        self.timeout_spin.setSingleStep(1000)
        self.timeout_spin.setSuffix(" ms")

        self.screenshot_settle_spin = QSpinBox()
        self.screenshot_settle_spin.setRange(0, 10000)
        self.screenshot_settle_spin.setSingleStep(50)
        self.screenshot_settle_spin.setSuffix(" ms")

        self.screenshot_root_edit = QLineEdit()
        self.screenshot_root_edit.setPlaceholderText("Optional custom screenshot root directory")

        form.addRow("Mode", self.mode_combo)
        form.addRow("Resource", self.resource_edit)
        form.addRow("Timeout", self.timeout_spin)
        form.addRow("Screenshot Settle", self.screenshot_settle_spin)
        form.addRow("Screenshot Root", self.screenshot_root_edit)

        layout.addWidget(box)

        btn_row = QHBoxLayout()
        self.btn_test = QPushButton("Test Connection")
        self.btn_apply = QPushButton("Apply")
        self.btn_save = QPushButton("Save")
        btn_row.addWidget(self.btn_test)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_apply)
        btn_row.addWidget(self.btn_save)
        layout.addLayout(btn_row)

        self.status_label = QLabel("Idle")
        self.detail_box = QTextEdit()
        self.detail_box.setReadOnly(True)
        self.detail_box.setMinimumHeight(120)
        layout.addWidget(self.status_label)
        layout.addWidget(self.detail_box, 1)

        self.mode_combo.currentTextChanged.connect(self._sync_enabled_state)
        self.btn_test.clicked.connect(self.on_test_connection)
        self.btn_apply.clicked.connect(self.on_apply)
        self.btn_save.clicked.connect(self.on_save)

        self._sync_enabled_state()

    def _sync_enabled_state(self) -> None:
        mode = self.mode_combo.currentText().upper()
        enable_resource = mode in ("AUTO", "SCPI")
        self.resource_edit.setEnabled(enable_resource)
        self.timeout_spin.setEnabled(enable_resource)

    def get_settings(self) -> Dict:
        return {
            "mode": self.mode_combo.currentText().upper(),
            "resource_name": self.resource_edit.text().strip(),
            "timeout_ms": int(self.timeout_spin.value()),
            "screenshot_settle_ms": int(self.screenshot_settle_spin.value()),
            "screenshot_root_dir": self.screenshot_root_edit.text().strip(),
        }

    def set_settings(self, settings: Dict) -> None:
        mode = str(settings.get("mode", "AUTO")).upper()
        idx = self.mode_combo.findText(mode)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.resource_edit.setText(str(settings.get("resource_name", "")))
        self.timeout_spin.setValue(int(settings.get("timeout_ms", 10000)))
        self.screenshot_settle_spin.setValue(int(settings.get("screenshot_settle_ms", 300)))
        self.screenshot_root_edit.setText(str(settings.get("screenshot_root_dir", "")))
        self._sync_enabled_state()

    def _build_factory(self):
        s = self.get_settings()
        mode = s["mode"]
        if mode == "DUMMY":
            return DummyInstrumentFactory()
        if mode == "SCPI":
            return ScpiInstrumentFactory(
                resource_name=s["resource_name"],
                timeout_ms=s["timeout_ms"],
            )
        return AutoInstrumentFactory(
            resource_name=s["resource_name"] or None,
            timeout_ms=s["timeout_ms"],
        )

    def on_test_connection(self) -> None:
        s = self.get_settings()
        mode = s["mode"]

        try:
            factory = self._build_factory()
            inst = factory.create_measurement_instrument()

            connected = getattr(inst, "is_connected", None)
            if mode == "DUMMY":
                self.status_label.setText("Dummy driver ready")
                self.detail_box.setPlainText("Dummy instrument does not require a connection.")
                return

            if connected is True:
                self.status_label.setText("Connected")
                self.detail_box.setPlainText(
                    f"Connection succeeded.\nMode: {mode}\nResource: {s['resource_name']}"
                )
            else:
                err = getattr(inst, "last_connect_error", None)
                self.status_label.setText("Not connected")
                self.detail_box.setPlainText(
                    f"Connection was not established.\nMode: {mode}\nResource: {s['resource_name']}\nError: {err or 'Unknown'}"
                )

            if hasattr(inst, "disconnect"):
                try:
                    inst.disconnect()
                except Exception:
                    pass

        except Exception as e:
            self.status_label.setText("Connection test failed")
            self.detail_box.setPlainText(str(e))
            QMessageBox.warning(self, "Connection test failed", str(e))

    def on_apply(self) -> None:
        try:
            factory = self._build_factory()
            self.apply_factory_callback(factory)
            self.status_label.setText("Applied")
            self.detail_box.setPlainText("Instrument factory applied to runtime. New runs will use this setting.")
        except Exception as e:
            QMessageBox.warning(self, "Apply failed", str(e))

    def on_save(self) -> None:
        try:
            settings = self.get_settings()
            self.save_settings_callback(settings)
            self.status_label.setText("Saved")
            self.detail_box.setPlainText("Settings saved. You can also click Apply to use them immediately.")
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))
