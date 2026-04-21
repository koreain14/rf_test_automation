from __future__ import annotations

import ipaddress
import json

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.device_models import DeviceInfo, DEVICE_TYPES, DRIVER_CHOICES
from ui.workers.device_scan_worker import DeviceScanWorker
from ui.switch_ports_editor_dialog import SwitchPortsEditorDialog


class DeviceManagerTab(QWidget):
    def __init__(self, device_registry, instrument_manager, parent=None):
        super().__init__(parent)
        self.device_registry = device_registry
        self.instrument_manager = instrument_manager
        self._last_scan_results = []
        self._scan_worker = None
        self._build_ui()
        self.reload_devices()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_scan = QPushButton("Scan VISA")
        self.btn_cancel_scan = QPushButton("Cancel Scan")
        self.btn_cancel_scan.setEnabled(False)
        self.btn_reload = QPushButton("Reload")
        self.btn_test = QPushButton("Test")
        self.btn_delete = QPushButton("Delete")
        top.addWidget(self.btn_scan)
        top.addWidget(self.btn_cancel_scan)
        top.addWidget(self.btn_reload)
        top.addWidget(self.btn_test)
        top.addWidget(self.btn_delete)
        top.addStretch(1)
        layout.addLayout(top)

        self.scan_table = QTableWidget(0, 6)
        self.scan_table.setHorizontalHeaderLabels(["Resource", "Model", "Serial", "Type", "Driver", "Status"])
        self.scan_table.horizontalHeader().setStretchLastSection(True)
        self.scan_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scan_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.scan_table.setMinimumHeight(120)
        layout.addWidget(QLabel("Scan Results"))
        layout.addWidget(self.scan_table, 1)

        hint = QLabel("Tip: click a scan row to auto-fill the form, double-click to add it directly as a device. Test also works on unsaved form values.")
        layout.addWidget(hint)

        grid = QGridLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Driver", "Resource", "Enabled"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setMinimumHeight(220)
        grid.addWidget(self.table, 0, 0)

        editor = QWidget()
        form = QFormLayout(editor)
        self.name_edit = QLineEdit()
        self.type_combo = QComboBox()
        self.type_combo.addItems(DEVICE_TYPES)
        self.driver_combo = QComboBox()
        self.driver_combo.addItems(DRIVER_CHOICES)
        self.resource_edit = QLineEdit()

        self.tcpip_box = QGroupBox("Manual TCPIP")
        tcpip_form = QFormLayout(self.tcpip_box)
        self.tcpip_ip_edit = QLineEdit()
        self.tcpip_ip_edit.setPlaceholderText("192.168.0.10")
        self.tcpip_mode_combo = QComboBox()
        self.tcpip_mode_combo.addItems(["INSTR", "SOCKET"])
        self.tcpip_port_spin = QSpinBox()
        self.tcpip_port_spin.setRange(1, 65535)
        self.tcpip_port_spin.setValue(5025)
        self.tcpip_resource_preview = QLineEdit()
        self.tcpip_resource_preview.setReadOnly(True)
        self.btn_build_tcpip = QPushButton("Build Resource")
        self.btn_test_tcpip = QPushButton("Test TCPIP")
        self.btn_use_tcpip = QPushButton("Use In Form")

        tcpip_btns = QHBoxLayout()
        tcpip_btns.addWidget(self.btn_build_tcpip)
        tcpip_btns.addWidget(self.btn_test_tcpip)
        tcpip_btns.addWidget(self.btn_use_tcpip)

        tcpip_form.addRow("IP Address", self.tcpip_ip_edit)
        tcpip_form.addRow("Connection", self.tcpip_mode_combo)
        tcpip_form.addRow("Port", self.tcpip_port_spin)
        tcpip_form.addRow("Resource", self.tcpip_resource_preview)
        tcpip_form.addRow(tcpip_btns)

        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(True)
        self.desc_edit = QLineEdit()
        self.serial_edit = QLineEdit()
        self.options_edit = QPlainTextEdit()
        self.options_edit.setPlaceholderText('{"timeout_ms": 10000}')
        self.options_edit.setMinimumHeight(70)
        self.ports_edit = QPlainTextEdit()
        self.ports_edit.setPlaceholderText('[{"name": "ANT1", "command": "ROUTE 1"}]')
        self.ports_edit.setMinimumHeight(80)
        self.btn_edit_ports = QPushButton("Edit Switch Ports...")

        form.addRow("Name", self.name_edit)
        form.addRow("Type", self.type_combo)
        form.addRow("Driver", self.driver_combo)
        form.addRow("Resource", self.resource_edit)
        form.addRow("", self.tcpip_box)
        form.addRow("", self.enabled_check)
        form.addRow("Description", self.desc_edit)
        form.addRow("Serial", self.serial_edit)
        form.addRow("Options JSON", self.options_edit)
        form.addRow("Ports JSON", self.ports_edit)
        form.addRow("", self.btn_edit_ports)

        btns = QHBoxLayout()
        self.btn_new = QPushButton("New")
        self.btn_save = QPushButton("Save")
        btns.addWidget(self.btn_new)
        btns.addWidget(self.btn_save)
        form.addRow(btns)

        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setWidget(editor)
        editor_scroll.setMinimumWidth(420)
        grid.addWidget(editor_scroll, 0, 1)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        layout.addWidget(QLabel("Registered Devices"))
        layout.addLayout(grid, 2)

        self.status_label = QLabel("Ready")
        self.output_box = QPlainTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMinimumHeight(90)
        self.output_box.setMaximumHeight(140)
        layout.addWidget(self.status_label)
        layout.addWidget(self.output_box, 1)

        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.scan_table.itemSelectionChanged.connect(self.on_scan_selection_changed)
        self.scan_table.itemDoubleClicked.connect(self.on_scan_double_clicked)

        self.btn_new.clicked.connect(self.on_new)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_reload.clicked.connect(self.reload_devices)
        self.btn_scan.clicked.connect(self.on_scan)
        self.btn_cancel_scan.clicked.connect(self.on_cancel_scan)
        self.btn_edit_ports.clicked.connect(self.on_edit_ports)
        self.btn_test.clicked.connect(self.on_test)
        self.tcpip_mode_combo.currentTextChanged.connect(self._sync_tcpip_mode_state)
        self.btn_build_tcpip.clicked.connect(self.on_build_tcpip)
        self.btn_test_tcpip.clicked.connect(self.on_test_tcpip)
        self.btn_use_tcpip.clicked.connect(self.on_use_tcpip)

        self._sync_tcpip_mode_state()
        self._refresh_tcpip_resource_preview()

    def _parse_json_text(self, text: str, fallback):
        raw = text.strip()
        if not raw:
            return fallback
        return json.loads(raw)

    def _sync_tcpip_mode_state(self) -> None:
        is_socket = self.tcpip_mode_combo.currentText().upper() == "SOCKET"
        self.tcpip_port_spin.setEnabled(is_socket)
        self._refresh_tcpip_resource_preview()

    def _validate_tcpip_manual_inputs(self) -> tuple[str, str, int | None]:
        raw_ip = self.tcpip_ip_edit.text().strip()
        if not raw_ip:
            raise ValueError("IP address is required.")

        try:
            ip_text = str(ipaddress.ip_address(raw_ip))
        except ValueError as exc:
            raise ValueError("Enter a valid IPv4 or IPv6 address.") from exc

        mode = self.tcpip_mode_combo.currentText().upper()
        if mode == "SOCKET":
            return ip_text, mode, int(self.tcpip_port_spin.value())
        return ip_text, "INSTR", None

    def _build_tcpip_resource_string(self) -> str:
        ip_text, mode, port = self._validate_tcpip_manual_inputs()
        if mode == "SOCKET":
            return f"TCPIP0::{ip_text}::{port}::SOCKET"
        return f"TCPIP0::{ip_text}::inst0::INSTR"

    def _refresh_tcpip_resource_preview(self) -> str:
        try:
            resource = self._build_tcpip_resource_string()
        except Exception:
            resource = ""
        self.tcpip_resource_preview.setText(resource)
        return resource

    def _build_manual_probe_result(self, resource: str) -> dict:
        result = dict(self.instrument_manager.discovery.identify_tcpip_resource(resource, timeout_ms=10000) or {})
        result["resource"] = resource
        return result

    def _apply_manual_probe_result(self, result: dict) -> None:
        self.resource_edit.setText(str(result.get("resource", "")).strip())
        self.serial_edit.setText(str(result.get("serial_number", "")).strip())

        guessed_type = str(result.get("type", "")).strip()
        guessed_driver = str(result.get("driver", "")).strip()
        if guessed_type and guessed_type != "unknown" and self.type_combo.findText(guessed_type) >= 0:
            self.type_combo.setCurrentText(guessed_type)
        if guessed_driver and self.driver_combo.findText(guessed_driver) >= 0:
            self.driver_combo.setCurrentText(guessed_driver)

        idn = str(result.get("idn", "")).strip()
        if idn:
            self.desc_edit.setText(idn)

        if not self.name_edit.text().strip() and (guessed_type or guessed_driver or idn):
            self.name_edit.setText(self._suggest_name_from_scan(result))

    def _device_from_form(self) -> DeviceInfo:
        return DeviceInfo(
            name=self.name_edit.text().strip(),
            type=self.type_combo.currentText(),
            driver=self.driver_combo.currentText(),
            resource=self.resource_edit.text().strip(),
            enabled=self.enabled_check.isChecked(),
            description=self.desc_edit.text().strip(),
            serial_number=self.serial_edit.text().strip(),
            options=dict(self._parse_json_text(self.options_edit.toPlainText(), {})),
            ports=list(self._parse_json_text(self.ports_edit.toPlainText(), [])),
        )

    def _load_form(self, device: DeviceInfo | None) -> None:
        if not device:
            self.name_edit.clear()
            self.type_combo.setCurrentIndex(0)
            self.driver_combo.setCurrentIndex(0)
            self.resource_edit.clear()
            self.enabled_check.setChecked(True)
            self.desc_edit.clear()
            self.serial_edit.clear()
            self.options_edit.setPlainText("{}")
            self.ports_edit.setPlainText("[]")
            self.tcpip_ip_edit.clear()
            self.tcpip_mode_combo.setCurrentText("INSTR")
            self.tcpip_port_spin.setValue(5025)
            self._refresh_tcpip_resource_preview()
            return

        self.name_edit.setText(device.name)
        self.type_combo.setCurrentText(device.type)
        self.driver_combo.setCurrentText(device.driver)
        self.resource_edit.setText(device.resource)
        self.enabled_check.setChecked(device.enabled)
        self.desc_edit.setText(device.description)
        self.serial_edit.setText(getattr(device, "serial_number", ""))
        self.options_edit.setPlainText(json.dumps(device.options, ensure_ascii=False, indent=2))
        self.ports_edit.setPlainText(json.dumps(device.ports, ensure_ascii=False, indent=2))
        self._refresh_tcpip_resource_preview()

    def reload_devices(self) -> None:
        devices = self.device_registry.list_devices()
        self.table.setRowCount(len(devices))
        for row, d in enumerate(devices):
            self.table.setItem(row, 0, QTableWidgetItem(d.name))
            self.table.setItem(row, 1, QTableWidgetItem(d.type))
            self.table.setItem(row, 2, QTableWidgetItem(d.driver))
            self.table.setItem(row, 3, QTableWidgetItem(d.resource))
            self.table.setItem(row, 4, QTableWidgetItem("Y" if d.enabled else "N"))
        self.status_label.setText(f"{len(devices)} device(s) loaded")

    def selected_device_name(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text().strip() if item else None

    def selected_scan_result(self) -> dict | None:
        rows = self.scan_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._last_scan_results):
            return self._last_scan_results[row]
        return None

    def _suggest_name_from_scan(self, scan_result: dict) -> str:
        model = str(scan_result.get("model", "")).strip()
        guessed_driver = str(scan_result.get("driver", "")).strip()
        guessed_type = str(scan_result.get("type", "")).strip()
        base_name = (model or guessed_driver or guessed_type or "DEVICE").upper()
        base_name = base_name.replace(" ", "_").replace("-", "_")

        existing = {d.name.upper() for d in self.device_registry.list_devices()}
        if base_name.upper() not in existing:
            return base_name

        idx = 2
        while True:
            candidate = f"{base_name}_{idx:02d}"
            if candidate.upper() not in existing:
                return candidate
            idx += 1

    def _apply_scan_result_to_form(self, r: dict) -> None:
        self.resource_edit.setText(str(r.get("resource", "")))
        self.serial_edit.setText(str(r.get("serial_number", "")))

        guessed_type = str(r.get("type", "")).strip()
        guessed_driver = str(r.get("driver", "")).strip()
        if guessed_type and self.type_combo.findText(guessed_type) >= 0:
            self.type_combo.setCurrentText(guessed_type)
        if guessed_driver and self.driver_combo.findText(guessed_driver) >= 0:
            self.driver_combo.setCurrentText(guessed_driver)

        idn = str(r.get("idn", "")).strip()
        if idn:
            self.desc_edit.setText(idn)

        self.name_edit.setText(self._suggest_name_from_scan(r))

    def on_table_selection_changed(self) -> None:
        name = self.selected_device_name()
        device = self.device_registry.get_device(name) if name else None
        self._load_form(device)

    def on_scan_selection_changed(self) -> None:
        r = self.selected_scan_result()
        if not r:
            return
        self._apply_scan_result_to_form(r)
        self.output_box.setPlainText(json.dumps(r, ensure_ascii=False, indent=2))
        self.status_label.setText("Scan result applied to form")

    def on_scan_double_clicked(self, item) -> None:
        r = self.selected_scan_result()
        if not r:
            return
        self._apply_scan_result_to_form(r)
        self.on_save()

    def on_new(self) -> None:
        self._load_form(None)

    def on_save(self) -> None:
        try:
            device = self._device_from_form()
            if not device.name:
                raise ValueError("Name is required")
            if not device.resource and device.driver not in ("innco_co3000", "innco_mast"):
                raise ValueError("Resource is required")
            self.device_registry.upsert_device(device)
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return
        self.reload_devices()
        self.status_label.setText(f"Saved: {device.name}")

    def on_delete(self) -> None:
        name = self.selected_device_name()
        if not name:
            QMessageBox.information(self, "Delete", "Select a device first.")
            return
        self.device_registry.remove_device(name)
        self.reload_devices()
        self._load_form(None)
        self.status_label.setText(f"Deleted: {name}")

    def on_scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            QMessageBox.information(self, "Scan VISA", "A scan is already in progress.")
            return

        self._last_scan_results = []
        self.scan_table.setRowCount(0)
        self.output_box.setPlainText("Starting VISA scan...")
        self.status_label.setText("Scanning VISA resources...")
        self.btn_scan.setEnabled(False)
        self.btn_cancel_scan.setEnabled(True)

        self._scan_worker = DeviceScanWorker(self.instrument_manager.discovery, timeout_ms=1500)
        self._scan_worker.progress.connect(self.on_scan_progress)
        self._scan_worker.result_found.connect(self.on_scan_result_found)
        self._scan_worker.finished_scan.connect(self.on_scan_finished)
        self._scan_worker.error.connect(self.on_scan_error)
        self._scan_worker.start()

    def on_cancel_scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.request_cancel()
            self.status_label.setText("Cancelling scan...")

    def on_scan_progress(self, current: int, total: int, resource: str) -> None:
        total_txt = total if total > 0 else "?"
        self.status_label.setText(f"Scanning... {current} / {total_txt}")
        self.output_box.setPlainText(
            f"Scanning VISA resources...\n\n"
            f"Progress: {current} / {total_txt}\n"
            f"Current: {resource}"
        )

    def on_scan_result_found(self, r: dict) -> None:
        self._last_scan_results.append(r)
        row = self.scan_table.rowCount()
        self.scan_table.insertRow(row)
        self.scan_table.setItem(row, 0, QTableWidgetItem(str(r.get("resource", ""))))
        self.scan_table.setItem(row, 1, QTableWidgetItem(str(r.get("model", ""))))
        self.scan_table.setItem(row, 2, QTableWidgetItem(str(r.get("serial_number", ""))))
        self.scan_table.setItem(row, 3, QTableWidgetItem(str(r.get("type", ""))))
        self.scan_table.setItem(row, 4, QTableWidgetItem(str(r.get("driver", ""))))
        self.scan_table.setItem(row, 5, QTableWidgetItem(str(r.get("status", ""))))
        self.output_box.setPlainText(json.dumps(self._last_scan_results, ensure_ascii=False, indent=2))

    def on_scan_finished(self, count: int) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_cancel_scan.setEnabled(False)
        if count == 0:
            self.status_label.setText("Scan completed: no resources")
            self.output_box.setPlainText("No VISA resources found.")
        else:
            self.status_label.setText(f"Scan completed: {count} resource(s)")

    def on_scan_error(self, message: str) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_cancel_scan.setEnabled(False)
        self.status_label.setText("Scan failed")
        self.output_box.setPlainText(message)
        QMessageBox.warning(self, "Scan failed", message)

    def on_edit_ports(self) -> None:
        current_ports = []
        try:
            current_ports = list(self._parse_json_text(self.ports_edit.toPlainText(), []))
        except Exception:
            current_ports = []

        dlg = SwitchPortsEditorDialog(ports=current_ports, parent=self)
        if dlg.exec():
            ports = dlg.ports()
            self.ports_edit.setPlainText(json.dumps(ports, ensure_ascii=False, indent=2))
            self.status_label.setText(f"Switch ports updated: {len(ports)} row(s)")

    def on_build_tcpip(self) -> None:
        try:
            resource = self._build_tcpip_resource_string()
        except Exception as e:
            self.status_label.setText("TCPIP resource invalid")
            self.tcpip_resource_preview.clear()
            QMessageBox.warning(self, "Build TCPIP resource", str(e))
            return

        self.tcpip_resource_preview.setText(resource)
        self.status_label.setText("TCPIP resource ready")
        self.output_box.setPlainText(
            json.dumps(
                {
                    "resource": resource,
                    "connection_type": self.tcpip_mode_combo.currentText().upper(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    def on_use_tcpip(self) -> None:
        try:
            resource = self._build_tcpip_resource_string()
        except Exception as e:
            QMessageBox.warning(self, "Use TCPIP resource", str(e))
            return

        self.tcpip_resource_preview.setText(resource)
        self.resource_edit.setText(resource)
        self.status_label.setText("TCPIP resource applied to form")

    def on_test_tcpip(self) -> None:
        try:
            resource = self._build_tcpip_resource_string()
        except Exception as e:
            self.status_label.setText("TCPIP test failed")
            self.tcpip_resource_preview.clear()
            QMessageBox.warning(self, "Test TCPIP", str(e))
            return

        self.tcpip_resource_preview.setText(resource)
        result = self._build_manual_probe_result(resource)
        self.output_box.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))

        status = str(result.get("status", "")).strip()
        if status == "OK":
            self._apply_manual_probe_result(result)
            self.status_label.setText("TCPIP connection OK")
            return

        self.status_label.setText("TCPIP connection failed")
        QMessageBox.warning(self, "Test TCPIP", status or "Unknown error")

    def on_test(self) -> None:
        selected_name = self.selected_device_name()
        if selected_name:
            result = self.instrument_manager.test_device(selected_name)
        else:
            try:
                device = self._device_from_form()
            except Exception as e:
                QMessageBox.warning(self, "Test failed", str(e))
                return

            if not device.driver:
                QMessageBox.information(self, "Test", "Select a driver first.")
                return
            if not device.resource and device.driver not in ("innco_co3000", "innco_mast"):
                QMessageBox.information(self, "Test", "Enter a resource first.")
                return
            if not device.name:
                device.name = "TEMP_DEVICE"

            result = self.instrument_manager.test_device_info(device)

        self.output_box.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("ok"):
            self.status_label.setText("Connection OK")
        else:
            self.status_label.setText("Connection failed")
            QMessageBox.warning(self, "Test failed", result.get("error", "Unknown error"))



