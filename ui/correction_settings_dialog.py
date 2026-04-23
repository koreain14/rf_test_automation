from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from application.correction_runtime import normalize_correction_meta, resolve_runtime_correction


_DEFAULT_PORT_KEYS = ("PORT1", "PORT2", "PORT3", "PORT4")


class CorrectionSettingsDialog(QDialog):
    def __init__(
        self,
        *,
        initial: dict | None = None,
        current_bound_path: str | None = None,
        ruleset_test_types=None,
        ruleset_id: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Correction Settings")
        self.resize(520, 640)

        self._initial_raw = dict(initial or {})
        self._initial = normalize_correction_meta({"correction": self._initial_raw})
        self._current_bound_path = str(current_bound_path or "").strip()
        self._ruleset_id = str(ruleset_id or "").strip()
        self._initial_rx_enabled = bool(self._initial.get("rx_enabled", False))
        self._selected_measurement = self._resolve_initial_measurement()
        self._legacy_profile_name = str(self._initial.get("profile_name") or "").strip()
        self._legacy_manual_offset_db = float(self._initial.get("manual_offset_db") or 0.0)
        self._legacy_binding = dict(self._initial.get("binding") or {"type": "RF_PATH", "field": "antenna"})

        layout = QVBoxLayout(self)

        top_form = QFormLayout()

        self.enable_check = QCheckBox("Enable Correction")
        self.enable_check.setChecked(bool(self._initial.get("enabled", False)))
        top_form.addRow(self.enable_check)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Instrument", "instrument")
        self.mode_combo.addItem("Off", "off")
        initial_mode = str(self._initial.get("mode") or "instrument").strip().lower()
        self._set_combo_data(self.mode_combo, initial_mode if initial_mode in {"instrument", "off"} else "instrument")
        top_form.addRow("Mode", self.mode_combo)

        self.apply_model_combo = QComboBox()
        self.apply_model_combo.addItem("Auto by Measurement + Port", "auto")
        self.apply_model_combo.addItem("Manual Override", "manual")
        initial_apply_model = str(self._initial.get("apply_model") or "auto").strip().lower()
        self._set_combo_data(self.apply_model_combo, initial_apply_model if initial_apply_model in {"auto", "manual"} else "auto")
        top_form.addRow("Apply Model", self.apply_model_combo)

        self.measurement_combo = QComboBox()
        self.measurement_combo.addItem("TX", "TX")
        self.measurement_combo.addItem("RX", "RX")
        self._set_combo_data(self.measurement_combo, self._selected_measurement or "TX")
        top_form.addRow("Current Measurement", self.measurement_combo)

        self.bound_path_edit = QLineEdit()
        self.bound_path_edit.setReadOnly(True)
        self.bound_path_edit.setText(self._current_bound_path or "(None)")
        top_form.addRow("Current Path", self.bound_path_edit)

        layout.addLayout(top_form)

        base_group = QGroupBox("Base Factors")
        base_form = QFormLayout(base_group)
        self.tx_base_edit = QLineEdit(str(self._initial.get("tx_base_factor") or ""))
        self.rx_base_edit = QLineEdit(str(self._initial.get("rx_base_factor") or ""))
        base_form.addRow("Tx Base Factor", self.tx_base_edit)
        base_form.addRow("Rx Base Factor", self.rx_base_edit)
        layout.addWidget(base_group)

        ports_group = QGroupBox("Switch Port Factors")
        ports_layout = QGridLayout(ports_group)
        self.port_factor_edits: dict[str, QLineEdit] = {}
        port_values = dict(self._initial.get("switch_port_factors") or {})
        ordered_ports = self._ordered_port_keys(port_values)
        for row, port_key in enumerate(ordered_ports):
            label = QLabel(port_key.title().replace("Port", "Port "))
            edit = QLineEdit(str(port_values.get(port_key, "") or ""))
            self.port_factor_edits[port_key] = edit
            ports_layout.addWidget(label, row, 0)
            ports_layout.addWidget(edit, row, 1)
        layout.addWidget(ports_group)

        rx_group = QGroupBox("RX Control")
        rx_layout = QVBoxLayout(rx_group)
        self.rx_enabled_check = QCheckBox("Enable RX Correction")
        self.rx_enabled_check.setChecked(self._initial_rx_enabled)
        rx_layout.addWidget(self.rx_enabled_check)
        rx_help = QLabel("TX-capable tests always use Tx Base Factor. RX factor is applied only when this option is enabled.")
        rx_help.setWordWrap(True)
        rx_layout.addWidget(rx_help)
        layout.addWidget(rx_group)

        manual_group = QGroupBox("Manual Override")
        manual_form = QFormLayout(manual_group)
        manual_override = dict(self._initial.get("manual_override") or {})
        self.manual_override_check = QCheckBox("Enable manual override")
        self.manual_override_check.setChecked(bool(manual_override.get("enabled")) or self.apply_model_combo.currentData() == "manual")
        manual_form.addRow(self.manual_override_check)
        self.manual_set_edit = QLineEdit(str(manual_override.get("set_id") or ""))
        manual_form.addRow("Correction Set / Factor Group", self.manual_set_edit)
        layout.addWidget(manual_group)

        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        self.status_view = QPlainTextEdit()
        self.status_view.setReadOnly(True)
        self.status_view.setMaximumBlockCount(128)
        self.status_view.setMinimumHeight(220)
        status_layout.addWidget(self.status_view)
        layout.addWidget(status_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.enable_check.toggled.connect(self._refresh_ui_state)
        self.mode_combo.currentIndexChanged.connect(self._refresh_ui_state)
        self.apply_model_combo.currentIndexChanged.connect(self._refresh_ui_state)
        self.measurement_combo.currentIndexChanged.connect(self._refresh_summary)
        self.manual_override_check.toggled.connect(self._refresh_ui_state)
        self.tx_base_edit.textChanged.connect(self._refresh_summary)
        self.rx_base_edit.textChanged.connect(self._refresh_summary)
        self.manual_set_edit.textChanged.connect(self._refresh_summary)
        self.rx_enabled_check.toggled.connect(self._refresh_summary)
        for edit in self.port_factor_edits.values():
            edit.textChanged.connect(self._refresh_summary)

        self._refresh_ui_state()

    def _resolve_initial_measurement(self) -> str:
        if self._current_bound_path:
            return "TX"
        return "RX" if self._initial_rx_enabled else "TX"

    def _ordered_port_keys(self, port_values: dict[str, str]) -> list[str]:
        ordered: list[str] = list(_DEFAULT_PORT_KEYS)
        for key in port_values:
            normalized = str(key or "").strip().upper()
            if normalized and normalized not in ordered:
                ordered.append(normalized)
        return ordered

    def _preview_case(self):
        class _PreviewCase:
            def __init__(self, test_type: str):
                self.test_type = test_type
                self.key = ""

        selected_measurement = str(self.measurement_combo.currentData() or "TX")
        return _PreviewCase("RX" if selected_measurement == "RX" else "TXP")

    def _summary_lines(self) -> list[str]:
        settings = self.settings()
        preview_meta = {
            "rf_path": {
                "antenna": self._current_bound_path,
                "switch_path": self._current_bound_path,
            },
            "correction": settings,
        }
        resolved = resolve_runtime_correction(preview_meta, self._preview_case())

        lines = [
            f"Enabled: {'Yes' if settings.get('enabled') else 'No'}",
            f"Mode: {str(settings.get('mode') or '').upper()}",
            f"Apply Model: {str(settings.get('apply_model') or '').upper()}",
            f"RX Correction: {'Enabled' if settings.get('rx_enabled') else 'Disabled'}",
            f"Current Measurement: {resolved.get('current_measurement') or '(Unknown)'}",
            f"Current Path: {resolved.get('current_path') or '(None)'}",
            f"Resolved Factors: {', '.join(resolved.get('resolved_factors') or []) or '(None)'}",
            f"Applied Set(s) / Resolved Set: {', '.join(resolved.get('resolved_sets') or []) or resolved.get('resolved_set') or '(None)'}",
            f"Reason: {resolved.get('reason') or '(None)'}",
            "",
            "Base Factors",
            f"- TX: {settings.get('tx_base_factor') or '(None)'}",
            f"- RX: {settings.get('rx_base_factor') or '(None)'}",
            "",
            "Switch Port Factors",
        ]
        for port_key in self._ordered_port_keys(dict(settings.get("switch_port_factors") or {})):
            lines.append(f"- {port_key}: {settings.get('switch_port_factors', {}).get(port_key, '') or '(None)'}")
        lines.extend(
            [
                "",
                "Manual Override",
                f"- Enabled: {'Yes' if (settings.get('manual_override') or {}).get('enabled') else 'No'}",
                f"- Set: {(settings.get('manual_override') or {}).get('set_id') or '(None)'}",
            ]
        )
        if self._legacy_profile_name:
            lines.extend(
                [
                    "",
                    "Compatibility",
                    f"- Existing legacy profile metadata will be preserved in saved JSON: {self._legacy_profile_name}",
                ]
            )
        return lines

    def _refresh_ui_state(self, *_args) -> None:
        enabled = self.enable_check.isChecked()
        instrument_mode = str(self.mode_combo.currentData() or "instrument") == "instrument"
        manual_mode = str(self.apply_model_combo.currentData() or "auto") == "manual"
        manual_enabled = self.manual_override_check.isChecked() or manual_mode

        self.mode_combo.setEnabled(enabled)
        self.apply_model_combo.setEnabled(enabled and instrument_mode)
        self.measurement_combo.setEnabled(enabled and instrument_mode)
        self.tx_base_edit.setEnabled(enabled and instrument_mode)
        self.rx_base_edit.setEnabled(enabled and instrument_mode)
        self.rx_enabled_check.setEnabled(enabled and instrument_mode)
        for edit in self.port_factor_edits.values():
            edit.setEnabled(enabled and instrument_mode)
        self.manual_override_check.setEnabled(enabled and instrument_mode)
        self.manual_set_edit.setEnabled(enabled and instrument_mode and manual_enabled)
        self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        self.status_view.setPlainText("\n".join(self._summary_lines()))

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def settings(self) -> dict:
        switch_port_factors = {
            key: str(edit.text() or "").strip()
            for key, edit in self.port_factor_edits.items()
        }
        manual_override_enabled = self.manual_override_check.isChecked() or self.apply_model_combo.currentData() == "manual"
        return {
            "enabled": self.enable_check.isChecked(),
            "mode": str(self.mode_combo.currentData() or "instrument"),
            "apply_model": str(self.apply_model_combo.currentData() or "auto"),
            "tx_base_factor": str(self.tx_base_edit.text() or "").strip(),
            "rx_base_factor": str(self.rx_base_edit.text() or "").strip(),
            "rx_enabled": self.rx_enabled_check.isChecked(),
            "switch_port_factors": switch_port_factors,
            "manual_override": {
                "enabled": manual_override_enabled,
                "set_id": str(self.manual_set_edit.text() or "").strip(),
            },
            "binding": dict(self._legacy_binding or {"type": "RF_PATH", "field": "antenna"}),
            "manual_offset_db": float(self._legacy_manual_offset_db),
            "profile_name": self._legacy_profile_name,
            "version": 1,
        }
