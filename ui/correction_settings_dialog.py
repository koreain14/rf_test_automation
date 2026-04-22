from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from application.correction_profile_loader import CorrectionProfileLoader
from application.correction_profile_model import CorrectionFactorSet, CorrectionProfileDocument
from application.correction_runtime import (
    calculate_total_correction_db,
    correction_capability_for_test_type,
    filter_supported_correction_test_types,
    normalize_correction_meta,
)
from domain.test_item_registry import canonical_test_label


_LEGACY_DEFAULT_APPLIES_TO = ["CHP", "PSD", "OBW", "TXP"]
_CAPABILITY_UI_LABELS = {
    "DIRECT_DB": "direct dB",
    "PSD_CANONICAL_DB": "canonical dBm/MHz",
}


def _normalize_applies_to(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        normalized = str(value or "").strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


class CorrectionSettingsDialog(QDialog):
    def __init__(
        self,
        *,
        initial: dict | None = None,
        current_bound_path: str | None = None,
        ruleset_test_types: Iterable[str] | None = None,
        ruleset_id: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Correction Settings")
        self.resize(460, 480)

        self._loader = CorrectionProfileLoader()
        self._profiles_by_name = {
            str(profile.name or "").strip(): profile
            for profile in self._loader.list_profiles()
            if str(profile.name or "").strip()
        }
        self._initial = normalize_correction_meta({"correction": dict(initial or {})})
        self._current_bound_path = str(current_bound_path or "").strip()
        self._ruleset_id = str(ruleset_id or "").strip()
        self._legacy_default_applies_to = filter_supported_correction_test_types(_LEGACY_DEFAULT_APPLIES_TO)
        self._available_applies_to = self._resolve_available_applies_to(ruleset_test_types)
        self._initial_applies_to = _normalize_applies_to((initial or {}).get("applies_to") or self._initial.get("applies_to") or [])
        self._preserved_hidden_applies_to = [
            item for item in self._initial_applies_to if item not in self._available_applies_to
        ]
        self._applies_to_checks: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.enable_check = QCheckBox("Enable correction for this plan")
        self.enable_check.setChecked(bool(self._initial.get("enabled", False)))
        form.addRow(self.enable_check)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["DIRECT", "SWITCH"])
        mode = str(self._initial.get("mode") or "DIRECT").strip().upper() or "DIRECT"
        idx = self.mode_combo.findText(mode)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Mode", self.mode_combo)

        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self._reload_profile_options(selected_name=str(self._initial.get("profile_name") or ""))
        form.addRow("Profile Name", self.profile_combo)

        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-200.0, 200.0)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setValue(float(self._initial.get("manual_offset_db", 0.0) or 0.0))
        self.offset_spin.setSuffix(" dB")
        form.addRow("Manual Offset", self.offset_spin)

        self.applies_to_widget = QWidget()
        applies_to_layout = QVBoxLayout(self.applies_to_widget)
        applies_to_layout.setContentsMargins(0, 0, 0, 0)
        applies_to_layout.setSpacing(4)

        scope_text = "Available from current RuleSet"
        if self._ruleset_id:
            scope_text = f"Available from current RuleSet ({self._ruleset_id})"
        self.applies_to_scope_label = QLabel(scope_text)
        self.applies_to_scope_label.setWordWrap(True)
        applies_to_layout.addWidget(self.applies_to_scope_label)

        self.applies_to_help_label = QLabel("Correction-capable tests only")
        self.applies_to_help_label.setWordWrap(True)
        applies_to_layout.addWidget(self.applies_to_help_label)

        self.applies_to_checks_widget = QWidget()
        self.applies_to_checks_layout = QVBoxLayout(self.applies_to_checks_widget)
        self.applies_to_checks_layout.setContentsMargins(0, 0, 0, 0)
        self.applies_to_checks_layout.setSpacing(2)
        applies_to_layout.addWidget(self.applies_to_checks_widget)

        self.applies_to_empty_label = QLabel("No correction-capable tests found for the current RuleSet.")
        self.applies_to_empty_label.setWordWrap(True)
        applies_to_layout.addWidget(self.applies_to_empty_label)

        self.applies_to_hidden_label = QLabel()
        self.applies_to_hidden_label.setWordWrap(True)
        applies_to_layout.addWidget(self.applies_to_hidden_label)

        self.applies_to_edit = QLineEdit()
        self.applies_to_edit.setReadOnly(True)
        applies_to_layout.addWidget(self.applies_to_edit)

        form.addRow("Applies To", self.applies_to_widget)

        self.bound_path_edit = QLineEdit()
        self.bound_path_edit.setReadOnly(True)
        self.bound_path_edit.setText(self._current_bound_path or "(None)")
        form.addRow("Current Bound Path", self.bound_path_edit)

        self.binding_field_edit = QLineEdit()
        self.binding_field_edit.setReadOnly(True)
        self.binding_field_edit.setText("recipe.meta.rf_path.antenna -> switch_path fallback")
        form.addRow("Binding", self.binding_field_edit)

        layout.addLayout(form)

        summary_box = QWidget()
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(QLabel("Correction Summary"))
        self.summary_view = QPlainTextEdit()
        self.summary_view.setReadOnly(True)
        self.summary_view.setMaximumBlockCount(128)
        self.summary_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.summary_view.setMinimumHeight(220)
        summary_layout.addWidget(self.summary_view)
        layout.addWidget(summary_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.enable_check.toggled.connect(self._refresh_summary)
        self.mode_combo.currentTextChanged.connect(self._sync_mode_from_selection)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        self.offset_spin.valueChanged.connect(self._refresh_summary)

        self._rebuild_applies_to_checkboxes()
        self._sync_mode_from_selection()
        self._refresh_summary()

    def _resolve_available_applies_to(self, ruleset_test_types: Iterable[str] | None) -> list[str]:
        candidates = filter_supported_correction_test_types(ruleset_test_types)
        if candidates:
            return candidates
        fallback_source = self._initial.get("applies_to") or _LEGACY_DEFAULT_APPLIES_TO
        fallback = filter_supported_correction_test_types(fallback_source)
        return fallback or list(self._legacy_default_applies_to)

    def _default_visible_applies_to(self) -> list[str]:
        defaults = [item for item in self._legacy_default_applies_to if item in self._available_applies_to]
        return defaults or list(self._available_applies_to)

    def _selected_visible_applies_to(self) -> list[str]:
        out: list[str] = []
        for test_type in self._available_applies_to:
            checkbox = self._applies_to_checks.get(test_type)
            if checkbox is not None and checkbox.isChecked():
                out.append(test_type)
        return out

    def _effective_applies_to(self) -> list[str]:
        selected_visible = self._selected_visible_applies_to()
        if not selected_visible:
            selected_visible = self._default_visible_applies_to()
        out: list[str] = []
        seen: set[str] = set()
        for item in [*selected_visible, *self._preserved_hidden_applies_to]:
            normalized = str(item or "").strip().upper()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    def _checkbox_label(self, test_type: str) -> str:
        label = canonical_test_label(test_type)
        capability = correction_capability_for_test_type(test_type)
        capability_label = _CAPABILITY_UI_LABELS.get(capability, capability.replace("_", " ").lower())
        if label and label != test_type and capability_label:
            return f"{test_type} ({label}, {capability_label})"
        if capability_label:
            return f"{test_type} ({capability_label})"
        return test_type

    def _rebuild_applies_to_checkboxes(self) -> None:
        initial_selected = set(self._initial.get("applies_to") or [])
        default_selected = set(self._default_visible_applies_to())
        while self.applies_to_checks_layout.count():
            item = self.applies_to_checks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._applies_to_checks.clear()
        for test_type in self._available_applies_to:
            checkbox = QCheckBox(self._checkbox_label(test_type))
            checkbox.setChecked(test_type in initial_selected if initial_selected else test_type in default_selected)
            checkbox.toggled.connect(self._refresh_summary)
            self.applies_to_checks_layout.addWidget(checkbox)
            self._applies_to_checks[test_type] = checkbox

        self.applies_to_checks_widget.setVisible(bool(self._available_applies_to))
        self.applies_to_empty_label.setVisible(not bool(self._available_applies_to))
        if self._preserved_hidden_applies_to:
            preserved = ", ".join(self._preserved_hidden_applies_to)
            self.applies_to_hidden_label.setText(
                f"Existing non-visible selections are preserved for compatibility: {preserved}"
            )
            self.applies_to_hidden_label.setVisible(True)
        else:
            self.applies_to_hidden_label.clear()
            self.applies_to_hidden_label.setVisible(False)
        self._sync_applies_to_text()

    def _sync_applies_to_text(self) -> None:
        self.applies_to_edit.setText(", ".join(self._effective_applies_to()))

    def _reload_profile_options(self, selected_name: str | None = None) -> None:
        current_name = str(selected_name or "").strip()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        names = sorted(self._profiles_by_name.keys())
        for name in names:
            self.profile_combo.addItem(name, name)
        if current_name and current_name not in names:
            self.profile_combo.addItem(current_name, current_name)
        idx = self.profile_combo.findData(current_name)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        elif current_name:
            self.profile_combo.setEditText(current_name)
        self.profile_combo.blockSignals(False)

    def _current_profile(self) -> CorrectionProfileDocument | None:
        name = self.selected_profile_name()
        if not name:
            return None
        return self._profiles_by_name.get(name)

    def _selected_factor_set(self, profile: CorrectionProfileDocument | None) -> tuple[CorrectionFactorSet | None, str]:
        if profile is None:
            return None, ""
        mode = profile.normalized_mode()
        if mode == "DIRECT":
            return profile.factors, "DIRECT"
        bound = self._current_bound_path
        if not bound:
            return None, ""
        factor_set = dict(profile.ports or {}).get(bound)
        return factor_set, bound

    def _format_factor_lines(self, factor_set: CorrectionFactorSet | None) -> list[str]:
        if factor_set is None:
            return ["(No effective factors resolved)"]
        data = factor_set.to_dict()
        labels = [
            ("cable_loss_db", "Cable Loss"),
            ("attenuator_db", "Attenuation"),
            ("dut_cable_loss_db", "DUT Cable Loss"),
            ("switchbox_loss_db", "Switchbox Loss"),
            ("divider_loss_db", "Divider Loss"),
            ("external_gain_db", "External Gain"),
        ]
        out: list[str] = []
        for key, label in labels:
            value = float(data.get(key, 0.0) or 0.0)
            out.append(f"- {label}: {value:g} dB")
        return out

    def _summary_lines(self) -> Iterable[str]:
        enabled = self.enable_check.isChecked()
        selected_mode = self.mode_combo.currentText().strip() or "DIRECT"
        profile_name = self.selected_profile_name()
        offset = float(self.offset_spin.value())
        profile = self._current_profile()
        profile_mode = profile.normalized_mode() if profile is not None else ""
        factor_set, effective_key = self._selected_factor_set(profile)
        total_db, _breakdown = calculate_total_correction_db(factor_set, offset)

        yield f"Enabled: {'Yes' if enabled else 'No'}"
        yield f"Selected Mode: {selected_mode}"
        yield f"Profile: {profile_name or '(None)'}"
        yield f"Profile Description: {getattr(profile, 'description', '') or '(None)'}"
        yield f"Profile Mode: {profile_mode or '(Unknown)'}"
        yield f"Manual Offset: {offset:g} dB"
        yield f"Current Bound Path: {self._current_bound_path or '(None)'}"
        yield f"Applies To: {self.applies_to_edit.text() or '(None)'}"
        yield f"Binding: {self.binding_field_edit.text()}"
        yield ""

        if profile is None:
            yield "Effective Summary"
            yield "- Selected profile was not found in config/correction_profiles.json"
            return

        if profile.normalized_mode() == "SWITCH":
            yield "Effective Summary"
            if not self._current_bound_path:
                yield "- No RF Path is currently selected."
                yield "- SWITCH profile is loaded, but no port-specific factor can be resolved yet."
                return
            if factor_set is None:
                yield f"- Current path '{self._current_bound_path}' is not present in this SWITCH profile."
                yield f"- Available ports: {', '.join(sorted(dict(profile.ports or {}).keys())) or '(None)'}"
                return
            yield f"- Effective Port: {effective_key or self._current_bound_path}"
        else:
            yield "Effective Summary"
            yield "- Effective Path: DIRECT"

        for line in self._format_factor_lines(factor_set):
            yield line
        yield f"- Estimated Total Correction: {total_db:g} dB"

    def _sync_mode_from_selection(self, *_args) -> None:
        enabled = self.enable_check.isChecked()
        self.profile_combo.setEnabled(enabled)
        self.offset_spin.setEnabled(enabled)
        self.applies_to_widget.setEnabled(enabled)
        if not enabled:
            return

    def _on_profile_changed(self, *_args) -> None:
        profile = self._current_profile()
        if profile is not None:
            mode = profile.normalized_mode()
            idx = self.mode_combo.findText(mode)
            if idx >= 0 and self.mode_combo.currentIndex() != idx:
                self.mode_combo.blockSignals(True)
                self.mode_combo.setCurrentIndex(idx)
                self.mode_combo.blockSignals(False)
        self._sync_mode_from_selection()
        self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        self._sync_applies_to_text()
        self.summary_view.setPlainText("\n".join(self._summary_lines()))
        self._sync_mode_from_selection()

    def selected_profile_name(self) -> str:
        data = self.profile_combo.currentData()
        if data:
            return str(data).strip()
        return str(self.profile_combo.currentText() or "").strip()

    def settings(self) -> dict:
        return {
            "enabled": self.enable_check.isChecked(),
            "mode": str(self.mode_combo.currentText() or "DIRECT").strip().upper() or "DIRECT",
            "profile_name": self.selected_profile_name(),
            "binding": {
                "type": "RF_PATH",
                "field": "antenna",
            },
            "manual_offset_db": float(self.offset_spin.value()),
            "applies_to": self._effective_applies_to(),
            "version": 1,
        }
