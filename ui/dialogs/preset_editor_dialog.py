from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from application.migrations_preset import migrate_preset_to_latest
from application.measurement_profile_loader import MeasurementProfileLoader
from application.preset_migration import analyze_preset_model
from application.plan_builder_registry import PlanBuilderRegistry
from application.plan_builders.wlan_plan_builder import WlanPlanBuilder
from application.preset_validator_registry import PresetValidatorRegistry
from application.tech_registry import TechRegistry
from application.preset_model import (
    ChannelSelectionModel,
    ExecutionPolicyModel,
    PresetModel,
    PresetSelectionModel,
    WlanChannelRowModel,
    WlanExpansionModel,
    WlanModeRowModel,
)
from application.preset_repo import PresetFileInfo, PresetRepo
from application.preset_serializer import PresetSerializer
from application.preset_validator import PresetValidator
from application.psd_unit_policy import (
    PSD_UNIT_DBM_PER_MHZ,
    PSD_UNIT_MW_PER_MHZ,
    resolve_psd_result_unit,
)
from application.test_type_symbols import DEFAULT_TEST_ORDER, default_profile_for_test_type, normalize_profile_name, normalize_test_type_list, normalize_test_type_map
from domain.ruleset_models import (
    collect_ruleset_test_types,
    normalize_case_dimensions,
    normalize_data_rate_policy,
    normalize_voltage_policy,
    project_ruleset_test_contracts,
)
from domain.test_item_pool import get_test_item_definition, is_selectable_test_item
from domain.test_item_registry import canonical_test_label, normalize_test_id, normalize_test_id_list
from ui.preset_editors import WlanExpansionEditor


class PresetEditorDialog(QDialog):
    def __init__(
        self,
        preset_repo: PresetRepo,
        plan_repo=None,
        project_id: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.preset_repo = preset_repo
        self.plan_repo = plan_repo
        self.project_id = project_id
        self.validator = PresetValidator()
        self.measurement_profile_loader = MeasurementProfileLoader()
        self._current_file_info: PresetFileInfo | None = None
        self._current_model: PresetModel | None = None
        self._dirty = False
        self._loading_form = False
        self._validator_registry = self._build_validator_registry()
        self._builder_registry = self._build_builder_registry()
        self._tech_registry = self._build_tech_registry()
        self._wlan_builder = WlanPlanBuilder()
        self._test_checkbox_state: dict[str, dict[str, Any]] = {}
        self._current_migration = None
        self.last_imported_project_preset_id: str | None = None
        self.last_imported_project_preset_name: str | None = None
        self.last_saved_preset_path: str | None = None

        self.setWindowTitle("Preset Editor")
        self.resize(1260, 860)
        self._build_ui()
        self._load_preset_list()
        self._new_preset()

    def _build_validator_registry(self):
        registry = getattr(self.validator, "_registry", None)
        if registry is not None:
            return registry
        try:
            return PresetValidatorRegistry()
        except Exception:
            return None

    def _build_builder_registry(self):
        try:
            return PlanBuilderRegistry()
        except Exception:
            return None

    def _build_tech_registry(self):
        try:
            return TechRegistry(
                validator_registry=self._validator_registry,
                builder_registry=self._builder_registry,
            )
        except Exception:
            return None

    def _current_tech_descriptor(self, model: PresetModel | None = None):
        current_model = model or self._safe_get_model_from_form()
        registry = self._tech_registry
        if registry is None or current_model is None:
            return None
        try:
            return registry.resolve_descriptor(current_model)
        except Exception:
            return None

    def _current_extension_validators(self, model: PresetModel | None = None) -> list[Any]:
        current_model = model or self._safe_get_model_from_form()
        if current_model is None:
            return []

        registry = self._validator_registry
        if registry is not None and hasattr(registry, "resolve_validators"):
            try:
                validators = list(registry.resolve_validators(current_model))
                if validators:
                    return validators
            except Exception:
                pass

        if self._is_wlan_selected():
            wlan_validator = getattr(self.validator, "_wlan_validator", None)
            if wlan_validator is not None:
                return [wlan_validator]
        return []

    def _current_plan_builder(self, model: PresetModel | None = None):
        current_model = model or self._safe_get_model_from_form()
        if current_model is None:
            return None

        registry = self._tech_registry
        if registry is not None:
            try:
                builder = registry.get_builder_for_model(current_model)
                if builder is not None:
                    return builder
            except Exception:
                pass

        builder_registry = self._builder_registry
        if builder_registry is not None and hasattr(builder_registry, "resolve_builder"):
            try:
                builder = builder_registry.resolve_builder(current_model)
                if builder is not None:
                    return builder
            except Exception:
                pass

        if self._is_wlan_selected():
            return self._wlan_builder
        return None

    def _current_editor_factory(self, model: PresetModel | None = None):
        current_model = model or self._safe_get_model_from_form()
        registry = self._tech_registry
        if registry is None or current_model is None:
            return None
        try:
            return registry.get_editor_factory_for_model(current_model)
        except Exception:
            return None

    def _supports_registry_editor(self, model: PresetModel | None = None) -> bool:
        return self._current_editor_factory(model) is not None

    def _editor_factory_for_tech(self, tech_id: str):
        registry = self._tech_registry
        if registry is None:
            return None
        try:
            return registry.get_editor_factory_for_tech(tech_id)
        except Exception:
            return None

    def _create_registry_ready_wlan_editor(self, parent: QWidget):
        factory = self._editor_factory_for_tech("WLAN")
        if factory is not None:
            try:
                editor = factory(parent)
                if editor is not None:
                    return editor
            except Exception:
                pass
        return WlanExpansionEditor(parent)

    def _safe_get_model_from_form(self) -> PresetModel | None:
        try:
            return self._get_model_from_form()
        except Exception:
            return None

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Preset Library"))
        self.preset_list = QListWidget()
        left_layout.addWidget(self.preset_list, 1)

        btns = QHBoxLayout()
        self.btn_new = QPushButton("New")
        self.btn_copy = QPushButton("Copy")
        self.btn_delete = QPushButton("Delete")
        self.btn_import_file = QPushButton("Import JSON")
        btns.addWidget(self.btn_new)
        btns.addWidget(self.btn_copy)
        btns.addWidget(self.btn_delete)
        btns.addWidget(self.btn_import_file)
        left_layout.addLayout(btns)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs, 1)

        self._build_general_tab()
        self._build_wlan_tab()
        self._build_tests_tab()
        self._build_preview_tab()

        footer = QHBoxLayout()
        self.btn_validate = QPushButton("Validate")
        self.btn_save = QPushButton("Save")
        self.btn_save_as = QPushButton("Save As")
        self.btn_import_project = QPushButton("Import to Project")
        self.btn_close = QPushButton("Close")
        footer.addWidget(self.btn_validate)
        footer.addStretch(1)
        footer.addWidget(self.btn_save)
        footer.addWidget(self.btn_save_as)
        footer.addWidget(self.btn_import_project)
        footer.addWidget(self.btn_close)
        right_layout.addLayout(footer)
        splitter.addWidget(right)
        splitter.setSizes([290, 890])

        self.preset_list.currentItemChanged.connect(self._on_preset_selected)
        self.btn_new.clicked.connect(self._new_preset)
        self.btn_copy.clicked.connect(self._copy_current)
        self.btn_delete.clicked.connect(self._delete_current)
        self.btn_import_file.clicked.connect(self._import_from_json_file)
        self.btn_validate.clicked.connect(self._validate_current)
        self.btn_save.clicked.connect(self._save_current)
        self.btn_save_as.clicked.connect(lambda: self._save_current(force_save_as=True))
        self.btn_import_project.clicked.connect(self._import_to_project)
        self.btn_close.clicked.connect(self.accept)
        self.tabs.currentChanged.connect(lambda _: self._refresh_preview())
        self.cb_ruleset.currentTextChanged.connect(self._on_ruleset_changed)
        self.cb_ruleset.currentTextChanged.connect(self._update_expansion_visibility)
        self.cb_standard.currentTextChanged.connect(self._update_expansion_visibility)
        self.cb_ruleset.currentTextChanged.connect(self._refresh_psd_result_unit_hint)
        self.cb_band.currentTextChanged.connect(self._on_band_changed)
        self.cb_band.currentTextChanged.connect(self._refresh_psd_result_unit_hint)
        self.cb_psd_result_unit.currentTextChanged.connect(self._refresh_psd_result_unit_hint)
        self.btn_select_all_tests.clicked.connect(self._select_all_available_tests)
        self.btn_clear_all_tests.clicked.connect(self._clear_all_tests)
        self.btn_remove_disabled_tests.clicked.connect(self._remove_disabled_tests)
        self.btn_accept_auto_fixes.clicked.connect(self._accept_auto_fixes)
        self.btn_review_issues.clicked.connect(self._review_issues)
        self._connect_live_preview_signals()


    def _connect_live_preview_signals(self) -> None:
        def _connect(signal):
            signal.connect(self._mark_dirty_and_refresh)

        _connect(self.ed_name.textChanged)
        _connect(self.ed_description.textChanged)
        _connect(self.cb_ruleset.currentTextChanged)
        _connect(self.ed_ruleset_version.textChanged)
        _connect(self.cb_band.currentTextChanged)
        _connect(self.cb_standard.currentTextChanged)
        _connect(self.cb_plan_mode.currentTextChanged)
        _connect(self.cb_measurement_profile.currentTextChanged)
        _connect(self.cb_psd_result_unit.currentTextChanged)
        _connect(self.sp_nominal_voltage.valueChanged)
        _connect(self.ed_device_class.textChanged)
        _connect(self.ed_profiles_json.textChanged)
        _connect(self.cb_exec_type.currentTextChanged)
        _connect(self.ed_test_order.textChanged)
        _connect(self.chk_include_bw.toggled)
        self.wlan_editor.content_changed.connect(self._on_wlan_editor_changed)
        for cb in self.test_checks.values():
            cb.toggled.connect(self._mark_dirty_and_refresh)

    def _on_wlan_editor_changed(self) -> None:
        if self._loading_form:
            return
        primary = self.wlan_editor.primary_standard()
        if primary and self._is_wlan_selected() and self.cb_standard.currentText().strip() != primary:
            self.cb_standard.setCurrentText(primary)
        self._mark_dirty_and_refresh()

    def _mark_dirty_and_refresh(self, *_args) -> None:
        if self._loading_form:
            return
        self._dirty = True
        self._refresh_preview()

    def _build_general_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        guide = QLabel(
            "This preset applies one RuleSet. The selected RuleSet defines available bands, "
            "standards, axis defaults, and policy defaults. The preset then narrows that RuleSet "
            "to the exact test scope you want to run."
        )
        guide.setWordWrap(True)
        guide.setStyleSheet(
            "background:#e8eff4; border:1px solid #bcc9d4; border-radius:8px; "
            "padding:10px; color:#22313c;"
        )
        layout.addWidget(guide)

        ruleset_grp = QGroupBox("RuleSet Binding")
        ruleset_layout = QVBoxLayout(ruleset_grp)
        ruleset_form = QFormLayout()
        self.ed_name = QLineEdit()
        self.ed_description = QTextEdit()
        self.ed_description.setFixedHeight(80)
        self.cb_ruleset = QComboBox(); self.cb_ruleset.setEditable(True)
        self.ed_ruleset_version = QLineEdit("2026.02")
        self.cb_band = QComboBox(); self.cb_band.setEditable(True)
        self.lb_standard = QLabel("Standard")
        self.cb_standard = QComboBox(); self.cb_standard.setEditable(True)
        self.cb_plan_mode = QComboBox(); self.cb_plan_mode.addItems(["DEMO", "Quick", "Worst", "Full"])
        self.cb_measurement_profile = QComboBox()
        self.cb_measurement_profile.setEditable(False)
        self.cb_psd_result_unit = QComboBox()
        self.cb_psd_result_unit.addItem("(Ruleset Default)", "")
        self.cb_psd_result_unit.addItem("mW/MHz", PSD_UNIT_MW_PER_MHZ)
        self.cb_psd_result_unit.addItem("dBm/MHz", PSD_UNIT_DBM_PER_MHZ)
        self.lb_psd_result_unit_hint = QLabel("")
        self.lb_psd_result_unit_hint.setWordWrap(True)
        self.sp_nominal_voltage = QDoubleSpinBox()
        self.sp_nominal_voltage.setRange(0.0, 1000.0)
        self.sp_nominal_voltage.setDecimals(3)
        self.sp_nominal_voltage.setSingleStep(0.1)
        self.sp_nominal_voltage.setSuffix(" V")
        self.sp_nominal_voltage.setSpecialValueText("(empty)")
        self.ed_device_class = QLineEdit()
        self.lb_ruleset_summary = QLabel("")
        self.lb_ruleset_summary.setWordWrap(True)
        self.lb_ruleset_summary.setStyleSheet(
            "background:#f4f7fa; border:1px solid #d4dde6; border-radius:6px; "
            "padding:8px; color:#30404d;"
        )
        self.cb_ruleset.setToolTip("Select the RuleSet this preset will use at recipe/build time.")
        self.ed_ruleset_version.setToolTip("Preset-stored RuleSet version. Keep this aligned with the selected RuleSet file.")
        self.cb_band.setToolTip("Bands are loaded from the selected RuleSet when available.")
        self.cb_standard.setToolTip("Standards are filtered from the selected RuleSet and current band when available.")

        ruleset_form.addRow("RuleSet ID", self.cb_ruleset)
        ruleset_form.addRow("RuleSet Version", self.ed_ruleset_version)
        ruleset_form.addRow("Band", self.cb_band)
        ruleset_form.addRow(self.lb_standard, self.cb_standard)
        ruleset_layout.addLayout(ruleset_form)
        ruleset_layout.addWidget(self.lb_ruleset_summary)
        layout.addWidget(ruleset_grp)

        form_grp = QGroupBox("Preset Scope")
        form = QFormLayout(form_grp)
        form.addRow("Name", self.ed_name)
        form.addRow("Description", self.ed_description)
        form.addRow("Plan Mode", self.cb_plan_mode)
        form.addRow("Measurement Profile", self.cb_measurement_profile)
        form.addRow("PSD Result Unit", self.cb_psd_result_unit)
        form.addRow("", self.lb_psd_result_unit_hint)
        form.addRow("Nominal Voltage", self.sp_nominal_voltage)
        form.addRow("Device Class", self.ed_device_class)
        layout.addWidget(form_grp)

        self._reload_ruleset_options()
        self._reload_band_options()
        self._reload_standard_options()
        self._reload_measurement_profile_options()
        self._refresh_psd_result_unit_hint()
        self._refresh_ruleset_summary()
        self.tabs.addTab(tab, "General")

    def _build_wlan_tab(self) -> None:
        self.wlan_tab = QWidget()
        layout = QVBoxLayout(self.wlan_tab)
        guide = QLabel(
            "This tab is a preset generator for WLAN. One save can create many WLAN steps.\n"
            "Use a quick profile first, then adjust mode/channel rows only if needed."
        )
        guide.setWordWrap(True)
        layout.addWidget(guide)
        self.wlan_editor = self._create_registry_ready_wlan_editor(self.wlan_tab)
        layout.addWidget(self.wlan_editor)
        self.tabs.addTab(self.wlan_tab, "WLAN Expansion")

    def _build_tests_tab(self) -> None:
        tab = QWidget()
        self.tests_tab = tab
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        help_label = QLabel("Select test items included in the preset. Execution order is configured below in Execution Policy.")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.lb_migration_status = QLabel("")
        self.lb_migration_status.setWordWrap(True)
        layout.addWidget(self.lb_migration_status)
        controls = QVBoxLayout()
        controls_top = QHBoxLayout()
        controls_bottom = QHBoxLayout()
        self.btn_select_all_tests = QPushButton("Select All")
        self.btn_clear_all_tests = QPushButton("Clear All")
        self.btn_remove_disabled_tests = QPushButton("Remove Disabled Tests")
        self.btn_accept_auto_fixes = QPushButton("Accept Auto Fixes")
        self.btn_review_issues = QPushButton("Review Issues")
        for button in (
            self.btn_select_all_tests,
            self.btn_clear_all_tests,
            self.btn_remove_disabled_tests,
            self.btn_accept_auto_fixes,
            self.btn_review_issues,
        ):
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        controls_top.addWidget(self.btn_select_all_tests)
        controls_top.addWidget(self.btn_clear_all_tests)
        controls_top.addStretch(1)
        controls_bottom.addWidget(self.btn_remove_disabled_tests)
        controls_bottom.addWidget(self.btn_accept_auto_fixes)
        controls_bottom.addWidget(self.btn_review_issues)
        controls_bottom.addStretch(1)
        controls.addLayout(controls_top)
        controls.addLayout(controls_bottom)
        layout.addLayout(controls)
        self.test_checks: dict[str, QCheckBox] = {}
        self.lb_test_catalog_summary = QLabel("")
        self.lb_test_catalog_summary.setWordWrap(True)
        layout.addWidget(self.lb_test_catalog_summary)
        self.lb_test_catalog_warning = QLabel("")
        self.lb_test_catalog_warning.setWordWrap(True)
        layout.addWidget(self.lb_test_catalog_warning)
        test_splitter = QSplitter(Qt.Horizontal)
        test_splitter.setOpaqueResize(False)
        test_splitter.setHandleWidth(8)
        self.test_checks_scroll = QScrollArea()
        self.test_checks_scroll.setWidgetResizable(True)
        self.test_checks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.test_checks_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.test_checks_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.test_checks_scroll.setMinimumHeight(280)
        self.test_checks_widget = QWidget()
        self.test_checks_layout = QGridLayout(self.test_checks_widget)
        self.test_checks_layout.setContentsMargins(8, 8, 8, 8)
        self.test_checks_layout.setHorizontalSpacing(16)
        self.test_checks_layout.setVerticalSpacing(12)
        self.test_checks_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.test_checks_scroll.setWidget(self.test_checks_widget)
        test_splitter.addWidget(self.test_checks_scroll)
        issues_grp = QGroupBox("Compatibility Issues")
        issues_layout = QVBoxLayout(issues_grp)
        self.lb_issues_summary = QLabel("")
        self.lb_issues_summary.setWordWrap(True)
        issues_layout.addWidget(self.lb_issues_summary)
        self.ed_compatibility_issues = QPlainTextEdit()
        self.ed_compatibility_issues.setReadOnly(True)
        self.ed_compatibility_issues.setMinimumHeight(180)
        issues_layout.addWidget(self.ed_compatibility_issues, 1)
        issues_grp.setMinimumWidth(320)
        issues_grp.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        test_splitter.addWidget(issues_grp)
        test_splitter.setChildrenCollapsible(False)
        test_splitter.setSizes([700, 320])
        test_splitter.setStretchFactor(0, 3)
        test_splitter.setStretchFactor(1, 2)
        layout.addWidget(test_splitter, 3)

        profiles_grp = QGroupBox("Instrument Profiles")
        profiles_form = QFormLayout(profiles_grp)
        self.ed_profiles_json = QPlainTextEdit()
        self.ed_profiles_json.setMinimumHeight(120)
        self.ed_profiles_json.setPlaceholderText('{\n  "PSD": "PSD_DEFAULT"\n}')
        profiles_form.addRow("Profiles JSON", self.ed_profiles_json)

        exec_grp = QGroupBox("Execution Policy")
        exec_form = QFormLayout(exec_grp)
        self.cb_exec_type = QComboBox(); self.cb_exec_type.addItems(["CHANNEL_CENTRIC", "TEST_CENTRIC"])
        self.ed_test_order = QLineEdit(",".join(DEFAULT_TEST_ORDER))
        self.chk_include_bw = QCheckBox("Include BW in Group"); self.chk_include_bw.setChecked(True)
        exec_form.addRow("Type", self.cb_exec_type)
        exec_form.addRow("Test Order (CSV)", self.ed_test_order)
        exec_form.addRow("", self.chk_include_bw)
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)
        bottom_layout.addWidget(profiles_grp, 2)
        bottom_layout.addWidget(exec_grp, 1)
        layout.addLayout(bottom_layout)
        self._rebuild_test_checkboxes()
        self.tabs.addTab(tab, "Tests")

    def _build_preview_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        self.tabs.addTab(tab, "Preview")

    def _load_preset_list(self) -> None:
        self.preset_list.clear()
        for section, items in (("Built-in", self.preset_repo.list_builtin()), ("Custom", self.preset_repo.list_custom())):
            if not items:
                continue
            header = QListWidgetItem(section)
            header.setFlags(Qt.NoItemFlags)
            header.setData(Qt.UserRole, None)
            self.preset_list.addItem(header)
            for info in items:
                item = QListWidgetItem(f"{info.name} [{info.display_group}]")
                item.setData(Qt.UserRole, info)
                self.preset_list.addItem(item)

    def _on_preset_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        info = current.data(Qt.UserRole) if current else None
        if info is None:
            return
        try:
            model = self.preset_repo.load(info.path)
        except Exception as e:
            QMessageBox.warning(self, "Preset Load Failed", str(e))
            return
        self._current_file_info = info
        self._current_model = model
        self._set_form_from_model(model)
        self._dirty = False
        self._refresh_preview()

    def _new_preset(self) -> None:
        model = PresetModel(
            name="KC_WLAN_24G_PRESET",
            ruleset_id="KC_WLAN",
            ruleset_version="2026.02",
            description="",
            selection=PresetSelectionModel(
                band="2.4G",
                standard="802.11ax",
                plan_mode="Quick",
                measurement_profile_name="",
                nominal_voltage_v=None,
                test_types=[],
                execution_policy=ExecutionPolicyModel(type="CHANNEL_CENTRIC", test_order=list(DEFAULT_TEST_ORDER), include_bw_in_group=True),
                instrument_profile_by_test={},
                wlan_expansion=WlanExpansionModel(
                    mode_plan=[
                        WlanModeRowModel(standard="802.11b", phy_mode="DSSS", bandwidths_mhz=[20]),
                        WlanModeRowModel(standard="802.11g", phy_mode="OFDM", bandwidths_mhz=[20]),
                        WlanModeRowModel(standard="802.11n", phy_mode="HT", bandwidths_mhz=[20, 40]),
                        WlanModeRowModel(standard="802.11ax", phy_mode="HE", bandwidths_mhz=[20, 40]),
                    ],
                    channel_plan=[
                        WlanChannelRowModel(bandwidth_mhz=20, channels=[1, 6, 11], frequencies_mhz=[2412, 2437, 2462]),
                        WlanChannelRowModel(bandwidth_mhz=40, channels=[3, 11], frequencies_mhz=[2422, 2462]),
                    ],
                ),
            ),
        )
        self._current_file_info = None
        self._current_model = model
        self._set_form_from_model(model)
        self._dirty = True
        self._refresh_preview()

    def _copy_current(self) -> None:
        model = self._get_model_from_form()
        model.name = f"{model.name}_COPY"
        self._current_file_info = None
        self._current_model = model
        self._set_form_from_model(model)
        self._dirty = True
        self._refresh_preview()

    def _delete_current(self) -> None:
        if not self._current_file_info:
            QMessageBox.information(self, "Delete Preset", "Current preset has not been saved to the custom library.")
            return
        if self._current_file_info.is_builtin:
            QMessageBox.warning(self, "Delete Preset", "Built-in presets are read-only.")
            return
        ans = QMessageBox.question(self, "Delete Preset", f"Delete custom preset '{self._current_file_info.name}'?")
        if ans != QMessageBox.Yes:
            return
        try:
            self.preset_repo.delete(self._current_file_info.path)
        except Exception as e:
            QMessageBox.warning(self, "Delete Preset Failed", str(e))
            return
        self._load_preset_list()
        self._new_preset()

    def _import_from_json_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Preset JSON", "", "JSON Files (*.json)")
        if not file_path:
            return
        try:
            model = PresetSerializer.load_file(Path(file_path))
        except Exception as e:
            QMessageBox.warning(self, "Import Failed", str(e))
            return
        self._current_file_info = None
        self._current_model = model
        self._set_form_from_model(model)
        self._dirty = True
        self._refresh_preview()

    def _validate_current(self) -> None:
        model = self._get_model_from_form()
        result = self.validator.validate(model)
        if result.ok:
            QMessageBox.information(self, "Preset Validation", "Validation passed.\n\n" + result.summary())
        else:
            QMessageBox.warning(self, "Preset Validation", result.summary())

    def _save_current(self, force_save_as: bool = False) -> None:
        try:
            model = self._get_model_from_form()
            result = self.validator.validate(model)
        except Exception as e:
            QMessageBox.warning(self, "Preset Save Blocked", str(e))
            return
        if not result.ok:
            QMessageBox.warning(self, "Preset Save Blocked", result.summary())
            return
        if force_save_as or not self._current_file_info or self._current_file_info.is_builtin:
            file_name, _ = QFileDialog.getSaveFileName(
                self,
                "Save Preset As",
                str(self.preset_repo.custom_dir / f"{_slugify(model.name)}.json"),
                "JSON Files (*.json)",
            )
            if not file_name:
                return
            save_path = Path(file_name)
            PresetSerializer.save_file(model, save_path)
        else:
            save_path = self.preset_repo.save(model, self._current_file_info.path.name)

        self._current_file_info = PresetFileInfo(
            name=model.name,
            path=save_path,
            ruleset_id=model.ruleset_id,
            is_builtin=False,
            display_group="custom",
        )
        self._current_model = model
        self._dirty = False
        self._load_preset_list()
        self._refresh_preview()
        QMessageBox.information(self, "Preset Saved", f"Saved preset JSON:\n{save_path}")

    def _import_to_project(self) -> None:
        if not self.plan_repo or not self.project_id:
            QMessageBox.warning(self, "Import to Project", "No current project is available.")
            return
        try:
            model = self._get_model_from_form()
            result = self.validator.validate(model)
        except Exception as e:
            QMessageBox.warning(self, "Import Blocked", str(e))
            return
        if not result.ok:
            QMessageBox.warning(self, "Import Blocked", result.summary())
            return
        payload = PresetSerializer.to_dict(model)
        migrated, _ = migrate_preset_to_latest(payload)
        existing_id = self.plan_repo.find_preset_id_by_name(project_id=self.project_id, name=migrated["name"])
        self.last_imported_project_preset_name = migrated["name"]
        if existing_id:
            self.plan_repo.update_preset_json(preset_id=existing_id, preset_json=migrated)
            self.last_imported_project_preset_id = existing_id
            QMessageBox.information(self, "Preset Imported", f"Updated project preset: {migrated['name']}")
        else:
            new_preset_id = self.plan_repo.save_preset(
                project_id=self.project_id,
                name=migrated["name"],
                ruleset_id=migrated["ruleset_id"],
                ruleset_version=migrated["ruleset_version"],
                preset_json=migrated,
            )
            self.last_imported_project_preset_id = new_preset_id
            QMessageBox.information(self, "Preset Imported", f"Imported project preset: {migrated['name']}")
        self._dirty = False

    def _set_form_from_model(self, model: PresetModel) -> None:
        sel = model.selection
        self._loading_form = True
        try:
            self.ed_name.setText(model.name)
            self.ed_description.setPlainText(model.description)
            self._reload_ruleset_options(model.ruleset_id)
            self.cb_ruleset.setCurrentText(model.ruleset_id)
            self.ed_ruleset_version.setText(model.ruleset_version)
            self._reload_band_options(sel.band)
            self.cb_band.setCurrentText(sel.band)
            self._reload_standard_options(sel.standard)
            self.cb_standard.setCurrentText(sel.standard)
            self._rebuild_test_checkboxes(sel.test_types)
            self.cb_plan_mode.setCurrentText(sel.plan_mode)
            self._reload_measurement_profile_options(sel.measurement_profile_name)
            idx = self.cb_psd_result_unit.findData(sel.psd_result_unit or "")
            self.cb_psd_result_unit.setCurrentIndex(idx if idx >= 0 else 0)
            self.sp_nominal_voltage.setValue(float(sel.nominal_voltage_v or 0.0))
            self.ed_device_class.setText(sel.device_class)
            self.ed_profiles_json.setPlainText(json.dumps(sel.instrument_profile_by_test, ensure_ascii=False, indent=2))
            self.cb_exec_type.setCurrentText(sel.execution_policy.type)
            self.ed_test_order.setText(_csv(normalize_test_type_list(sel.execution_policy.test_order) or list(DEFAULT_TEST_ORDER)))
            self.chk_include_bw.setChecked(bool(sel.execution_policy.include_bw_in_group))
            selected_test_types = set(normalize_test_id_list(sel.test_types))
            for test_name, cb in self.test_checks.items():
                cb.setChecked(test_name in selected_test_types)
            self._update_expansion_visibility()
            self._refresh_ruleset_summary()
            self.wlan_editor.load_from_model(model)
        finally:
            self._refresh_psd_result_unit_hint()
            self._loading_form = False
        self._refresh_preview()


    def _select_preset_in_list(self, save_path: Path) -> None:
        target = str(save_path.resolve())
        for i in range(self.preset_list.count()):
            item = self.preset_list.item(i)
            info = item.data(Qt.UserRole)
            if info is None:
                continue
            try:
                if str(Path(info.path).resolve()) == target:
                    self.preset_list.setCurrentRow(i)
                    return
            except Exception:
                continue

    def _get_model_from_form(self, selected_tests_override: list[str] | None = None) -> PresetModel:
        selected_tests = (
            normalize_test_id_list(selected_tests_override)
            if selected_tests_override is not None
            else [name for name, cb in self.test_checks.items() if cb.isChecked()]
        )
        measurement_profile_name = self._selected_measurement_profile_name()
        instrument_profile_by_test = self._sanitize_instrument_profile_map(
            measurement_profile_name=measurement_profile_name,
            selected_tests=selected_tests,
            raw_map=_parse_json_object(self.ed_profiles_json.toPlainText()),
        )
        model = PresetModel(
            name=self.ed_name.text().strip(),
            description=self.ed_description.toPlainText().strip(),
            ruleset_id=self.cb_ruleset.currentText().strip(),
            ruleset_version=self.ed_ruleset_version.text().strip(),
            selection=PresetSelectionModel(
                band=self.cb_band.currentText().strip(),
                standard=self.cb_standard.currentText().strip(),
                plan_mode=self.cb_plan_mode.currentText().strip() or "DEMO",
                measurement_profile_name=measurement_profile_name,
                psd_result_unit=str(self.cb_psd_result_unit.currentData() or "").strip(),
                nominal_voltage_v=self._selected_nominal_voltage(),
                test_types=normalize_test_type_list(selected_tests),
                execution_policy=ExecutionPolicyModel(
                    type=self.cb_exec_type.currentText().strip() or "CHANNEL_CENTRIC",
                    test_order=normalize_test_type_list(_parse_str_csv(self.ed_test_order.text())) or list(DEFAULT_TEST_ORDER),
                    include_bw_in_group=self.chk_include_bw.isChecked(),
                ),
                instrument_profile_by_test=instrument_profile_by_test,
                device_class=self.ed_device_class.text().strip(),
                metadata={},
            ),
        )
        if self._is_wlan_selected():
            self.wlan_editor.apply_to_model(model)
            _sync_selection_summary_from_wlan_expansion(model)
        return model

    def _refresh_preview(self) -> None:
        try:
            model = self._get_model_from_form()
            payload = PresetSerializer.to_dict(model)
            validation = self.validator.validate(model)
            migration = analyze_preset_model(model, self._load_ruleset_payload(model.ruleset_id))
            self._refresh_compatibility_ui(migration, pending_auto_fixes=self._pending_auto_fix_entries())

            sections: list[str] = []
            sections.append("# VALIDATION\n" + validation.summary())
            sections.append(
                "# PRESET MIGRATION\n"
                + json.dumps(
                    {
                        "status": migration.status,
                        "auto_fixes": migration.auto_fixes,
                        "warnings": migration.warnings,
                        "disabled_items": [
                            {
                                "field": item.field,
                                "value": item.value,
                                "reason": item.reason,
                            }
                            for item in migration.disabled_items
                        ],
                        "errors": migration.errors,
                        "effective_selection": migration.effective_selection,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            sections.append(
                "# AXIS-AWARE PRESET SUMMARY\n"
                + json.dumps(
                    self._build_axis_aware_summary(model),
                    ensure_ascii=False,
                    indent=2,
                )
            )

            descriptor = self._current_tech_descriptor(model)
            extension_validators = self._current_extension_validators(model)
            builder = self._current_plan_builder(model)
            sections.append(
                "# TECH REGISTRY CONTEXT\n"
                + json.dumps(
                    {
                        "registered_tech_ids": list(self._tech_registry.registered_tech_ids()) if self._tech_registry is not None else [],
                        "descriptor": {
                            "tech_id": getattr(descriptor, "tech_id", ""),
                            "display_name": getattr(descriptor, "display_name", ""),
                            "capabilities": dict(getattr(descriptor, "capabilities", {}) or {}),
                        } if descriptor is not None else None,
                        "resolved_extension_validators": [type(item).__name__ for item in extension_validators],
                        "resolved_plan_builder": type(builder).__name__ if builder is not None else "",
                        "resolved_editor_factory": getattr(self._current_editor_factory(model), "__name__", "") if self._current_editor_factory(model) is not None else "",
                        "supports_registry_editor": self._supports_registry_editor(model),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

            if builder is not None:
                steps = builder.build_steps(model)
                sample = steps[:12]
                explanation = (
                    "Technology preview builder works like this:\n"
                    "- Registry resolves a tech-specific preview builder\n"
                    "- The builder expands the current preset selection into preview steps\n"
                    "- Runtime recipe/expand flow remains unchanged"
                )
                preview_title = f"# {getattr(descriptor, 'display_name', 'TECH')} PLAN PREVIEW"
                sections.append(
                    preview_title + "\n"
                    + json.dumps(
                        {
                            "how_it_works": explanation,
                            "generated_step_count": len(steps),
                            "sample_steps": sample,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )

            sections.append("# PRESET JSON\n" + json.dumps(payload, ensure_ascii=False, indent=2))
            self.preview.setPlainText("\n\n".join(sections))
        except Exception as e:
            if hasattr(self, "lb_migration_status"):
                self.lb_migration_status.hide()
            if hasattr(self, "ed_compatibility_issues"):
                self.ed_compatibility_issues.setPlainText("")
            self.preview.setPlainText(f"<preview unavailable>\n{e}")

    def _refresh_migration_status_banner(self, migration) -> None:
        disabled = [item.value for item in migration.disabled_items]
        if migration.status == "clean":
            self.lb_migration_status.setText("Migration Status: clean. Raw preset and effective preset are aligned.")
            self.lb_migration_status.setStyleSheet(
                "background:#edf7ed; border:1px solid #8bc48a; border-radius:6px; padding:8px; color:#234f24;"
            )
            self.lb_migration_status.show()
            return

        if migration.status == "warning":
            text = "Migration Status: warning."
            if disabled:
                text += " Disabled from execution: " + ", ".join(disabled) + "."
            if migration.auto_fixes:
                text += " Auto-fixes: " + "; ".join(migration.auto_fixes) + "."
            if migration.warnings:
                text += " Notes: " + "; ".join(migration.warnings) + "."
            self.lb_migration_status.setText(text)
            self.lb_migration_status.setStyleSheet(
                "background:#fff4e5; border:1px solid #f5c36b; border-radius:6px; padding:8px; color:#8a4b08;"
            )
            self.lb_migration_status.show()
            return

        text = "Migration Status: invalid."
        if disabled:
            text += " Disabled from execution: " + ", ".join(disabled) + "."
        if migration.errors:
            text += " Execution is blocked until fixed: " + "; ".join(migration.errors) + "."
        self.lb_migration_status.setText(text)
        self.lb_migration_status.setStyleSheet(
            "background:#fdecea; border:1px solid #f1a8a0; border-radius:6px; padding:8px; color:#912018;"
        )
        self.lb_migration_status.show()

    def _update_expansion_visibility(self) -> None:
        is_wlan = self._is_wlan_selected()

        wlan_idx = self.tabs.indexOf(self.wlan_tab)
        if wlan_idx >= 0:
            self.tabs.setTabVisible(wlan_idx, is_wlan)

        self.lb_standard.setVisible(not is_wlan)
        self.cb_standard.setVisible(not is_wlan)
        self.cb_standard.setEnabled(True)

        if is_wlan:
            self.cb_standard.setToolTip(
                "For WLAN, standards are defined in WLAN Expansion > Mode Plan. "
                "The General tab standard field is hidden to avoid duplicate input."
            )
        else:
            self.cb_standard.setToolTip("Standards are filtered from the selected RuleSet and current band when available.")
        self._refresh_psd_result_unit_hint()

    def _is_wlan_selected(self) -> bool:
        rid = self.cb_ruleset.currentText().strip().upper()
        if "WLAN" in rid:
            return True

        primary = self.wlan_editor.primary_standard().strip().upper() if hasattr(self, "wlan_editor") else ""
        if primary.startswith("802.11"):
            return True

        std = self.cb_standard.currentText().strip().upper()
        return std.startswith("802.11")

    def _reload_measurement_profile_options(self, selected_name: str | None = None) -> None:
        current_name = normalize_profile_name(selected_name)
        self.cb_measurement_profile.blockSignals(True)
        self.cb_measurement_profile.clear()
        self.cb_measurement_profile.addItem("(Use Per-Test / Default)", "")

        profile_names: list[str] = []
        try:
            profile_names = [normalize_profile_name(doc.name) for doc in self.measurement_profile_loader.list_profiles()]
        except Exception:
            profile_names = []

        seen: set[str] = set()
        for name in profile_names:
            if not name or name in seen:
                continue
            seen.add(name)
            self.cb_measurement_profile.addItem(name, name)

        if current_name and current_name not in seen:
            self.cb_measurement_profile.addItem(f"[Missing] {current_name}", current_name)

        idx = self.cb_measurement_profile.findData(current_name)
        self.cb_measurement_profile.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_measurement_profile.blockSignals(False)

    def _selected_measurement_profile_name(self) -> str:
        data = self.cb_measurement_profile.currentData()
        if data is not None:
            return normalize_profile_name(data)
        return normalize_profile_name(self.cb_measurement_profile.currentText())

    def _selected_nominal_voltage(self) -> float | None:
        value = float(self.sp_nominal_voltage.value())
        return value if value > 0 else None

    def _list_ruleset_ids(self) -> list[str]:
        ruleset_dir = Path("rulesets")
        out: list[str] = []
        if not ruleset_dir.exists():
            return ["KC_WLAN"]
        for path in sorted(ruleset_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            ruleset_id = str(payload.get("id", "")).strip()
            if ruleset_id and ruleset_id not in out:
                out.append(ruleset_id)
        if "KC_WLAN" not in out:
            out.insert(0, "KC_WLAN")
        return out or ["KC_WLAN"]

    def _reload_ruleset_options(self, selected_ruleset: str | None = None) -> None:
        selected = str(selected_ruleset or self.cb_ruleset.currentText() or "").strip()
        options = self._list_ruleset_ids()
        self.cb_ruleset.blockSignals(True)
        self.cb_ruleset.clear()
        self.cb_ruleset.addItems(options)
        if selected and selected not in options:
            self.cb_ruleset.addItem(selected)
        self.cb_ruleset.setCurrentText(selected or (options[0] if options else "KC_WLAN"))
        self.cb_ruleset.blockSignals(False)

    def _reload_band_options(self, selected_band: str | None = None) -> None:
        selected = str(selected_band or self.cb_band.currentText() or "").strip()
        payload = self._load_ruleset_payload(self.cb_ruleset.currentText().strip())
        bands = [str(name).strip() for name in dict(payload.get("bands") or {}).keys() if str(name).strip()]
        if not bands:
            bands = ["2.4G", "5G", "6G"]
        self.cb_band.blockSignals(True)
        self.cb_band.clear()
        self.cb_band.addItems(bands)
        if selected and selected not in bands:
            self.cb_band.addItem(selected)
        self.cb_band.setCurrentText(selected or bands[0])
        self.cb_band.blockSignals(False)

    def _reload_standard_options(self, selected_standard: str | None = None) -> None:
        selected = str(selected_standard or self.cb_standard.currentText() or "").strip()
        payload = self._load_ruleset_payload(self.cb_ruleset.currentText().strip())
        standards: list[str] = []
        bands = dict(payload.get("bands") or {})
        selected_band = self.cb_band.currentText().strip()
        if selected_band and isinstance(bands.get(selected_band), dict):
            standards = [str(item).strip() for item in (bands.get(selected_band, {}) or {}).get("standards", []) if str(item).strip()]
        if not standards:
            all_seen: set[str] = set()
            for band_payload in bands.values():
                for item in (dict(band_payload or {}).get("standards") or []):
                    name = str(item).strip()
                    if name and name not in all_seen:
                        all_seen.add(name)
                        standards.append(name)
        if not standards:
            standards = ["802.11a", "802.11b", "802.11g", "802.11n", "802.11ac", "802.11ax"]
        self.cb_standard.blockSignals(True)
        self.cb_standard.clear()
        self.cb_standard.addItems(standards)
        if selected and selected not in standards:
            self.cb_standard.addItem(selected)
        self.cb_standard.setCurrentText(selected or standards[0])
        self.cb_standard.blockSignals(False)

    def _ruleset_test_catalog(self, payload: dict, selected_band: str, selected_tests: list[str] | None = None) -> dict[str, Any]:
        selected_test_ids = normalize_test_id_list(selected_tests or [])
        bands = dict(payload.get("bands") or {})
        band_payload = dict(bands.get(selected_band) or {}) if selected_band else {}
        supported_tests = normalize_test_id_list((band_payload.get("tests_supported") or []))
        if not supported_tests:
            supported_tests = []
            for item in bands.values():
                for test_id in normalize_test_id_list((dict(item or {}).get("tests_supported") or [])):
                    if test_id not in supported_tests:
                        supported_tests.append(test_id)

        projected_contracts = project_ruleset_test_contracts(
            payload.get("test_contracts") or {},
            tests_supported=collect_ruleset_test_types(payload),
        )
        contract_types = normalize_test_id_list(projected_contracts.keys())
        validated_tests = [test_id for test_id in supported_tests if test_id in contract_types]
        missing_contracts = [test_id for test_id in supported_tests if contract_types and test_id not in contract_types]
        orphan_contracts = [test_id for test_id in contract_types if supported_tests and test_id not in supported_tests]
        ruleset_tech = str(payload.get("tech", "")).strip().upper()
        available = [
            test_id
            for test_id in (validated_tests or supported_tests)
            if is_selectable_test_item(test_id, tech=ruleset_tech)
        ]
        invalid_selected: list[str] = []
        for test_id in selected_test_ids:
            if not test_id or test_id in available:
                continue
            invalid_selected.append(test_id)

        labels = dict(payload.get("test_labels") or {})
        descriptions: dict[str, str] = {}
        tooltips: dict[str, str] = {}
        measurement_classes: dict[str, str] = {}
        required_instruments: dict[str, list[str]] = {}
        for test_id in normalize_test_id_list(available + invalid_selected + supported_tests + contract_types):
            contract = projected_contracts.get(test_id, {})
            pool_item = get_test_item_definition(test_id) or {}
            description = str(
                contract.get("name")
                or labels.get(test_id)
                or pool_item.get("display_name")
                or canonical_test_label(test_id)
            ).strip()
            descriptions[test_id] = description
            measurement_class = str(contract.get("measurement_class") or pool_item.get("measurement_class") or "").strip()
            instruments = [str(item).strip() for item in (contract.get("required_instruments") or pool_item.get("required_instruments") or []) if str(item).strip()]
            measurement_classes[test_id] = measurement_class
            required_instruments[test_id] = instruments
            tooltip_lines = [
                f"Canonical ID: {test_id}",
                f"Display Name: {description}",
                f"Measurement Class: {measurement_class or '(unspecified)'}",
                f"Required Instruments: {', '.join(instruments) if instruments else '(none)'}",
            ]
            if invalid_selected and test_id in invalid_selected:
                tooltip_lines.append("Status: selected in preset, but not currently allowed by the selected RuleSet/band.")
            tooltips[test_id] = "\n".join(tooltip_lines)

        return {
            "available": available,
            "supported": supported_tests,
            "contract_types": contract_types,
            "missing_contracts": missing_contracts,
            "orphan_contracts": orphan_contracts,
            "descriptions": descriptions,
            "tooltips": tooltips,
            "measurement_classes": measurement_classes,
            "required_instruments": required_instruments,
            "invalid_selected": invalid_selected,
        }

    def _pending_auto_fix_entries(self) -> list[str]:
        entries: list[str] = []

        raw_order = _parse_str_csv(self.ed_test_order.text())
        for raw_value in raw_order:
            normalized = normalize_test_id(raw_value)
            if raw_value != normalized:
                entries.append(f"selection.execution_policy.test_order: '{raw_value}' -> '{normalized}'")

        raw_profile_map = _parse_json_object(self.ed_profiles_json.toPlainText())
        for raw_key in raw_profile_map.keys():
            normalized_key = normalize_test_id(raw_key)
            if normalized_key and normalized_key != str(raw_key).strip():
                entries.append(f"selection.instrument_profile_by_test: '{raw_key}' -> '{normalized_key}'")

        deduped: list[str] = []
        seen: set[str] = set()
        for item in entries:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _refresh_compatibility_ui(self, migration, *, pending_auto_fixes: list[str] | None = None) -> None:
        pending = list(pending_auto_fixes or [])
        self._current_migration = migration
        disabled_items = [item for item in migration.disabled_items if item.field == "test_types"]
        disabled_count = len(disabled_items)
        auto_fix_count = len(migration.auto_fixes) + len(pending)
        warning_count = len(migration.warnings)
        error_count = len(migration.errors)

        if migration.status == "clean":
            self.lb_migration_status.setText("Preset is fully compatible with the current RuleSet.")
            self.lb_migration_status.setStyleSheet(
                "background:#edf7ed; border:1px solid #8bc48a; border-radius:6px; padding:8px; color:#234f24;"
            )
        elif migration.status == "warning":
            self.lb_migration_status.setText(
                "This preset has compatibility warnings. "
                f"{disabled_count} disabled test(s), {auto_fix_count} auto-fix item(s), {warning_count} warning(s). "
                "Disabled tests stay in the raw preset but are excluded from execution."
            )
            self.lb_migration_status.setStyleSheet(
                "background:#fff4e5; border:1px solid #f5c36b; border-radius:6px; padding:8px; color:#8a4b08;"
            )
        else:
            self.lb_migration_status.setText(
                "This preset is not fully compatible with the current RuleSet. "
                f"{disabled_count} disabled test(s), {warning_count} warning(s), {error_count} blocking issue(s). "
                "Execution may be blocked until the issues are fixed."
            )
            self.lb_migration_status.setStyleSheet(
                "background:#fdecea; border:1px solid #f1a8a0; border-radius:6px; padding:8px; color:#912018;"
            )
        self.lb_migration_status.show()

        issue_lines: list[str] = []
        issue_lines.append("Disabled Tests")
        if disabled_items:
            for item in disabled_items:
                issue_lines.append(f"- {item.value}: {item.reason} [Excluded from execution]")
        else:
            issue_lines.append("- None")
        issue_lines.append("")
        issue_lines.append("Auto Fixes")
        if migration.auto_fixes or pending:
            for item in migration.auto_fixes:
                issue_lines.append(f"- {item}")
            for item in pending:
                issue_lines.append(f"- Pending form normalization: {item}")
        else:
            issue_lines.append("- None")
        issue_lines.append("")
        issue_lines.append("Warnings")
        if migration.warnings:
            for item in migration.warnings:
                issue_lines.append(f"- {item}")
        else:
            issue_lines.append("- None")
        if migration.errors:
            issue_lines.append("")
            issue_lines.append("Blocking Issues")
            for item in migration.errors:
                issue_lines.append(f"- {item}")

        self.lb_issues_summary.setText(
            f"Disabled: {disabled_count} | Auto Fixes: {auto_fix_count} | "
            f"Warnings: {warning_count} | Blocking: {error_count}"
        )
        self.ed_compatibility_issues.setPlainText("\n".join(issue_lines))
        self.btn_remove_disabled_tests.setEnabled(bool(disabled_items))
        self.btn_accept_auto_fixes.setEnabled(bool(migration.auto_fixes or pending))
        self.btn_review_issues.setEnabled(bool(disabled_items or migration.auto_fixes or pending or migration.warnings or migration.errors))

    def _remove_disabled_tests(self) -> None:
        disabled_selected = [
            test_id
            for test_id, state in self._test_checkbox_state.items()
            if state.get("disabled") and self.test_checks.get(test_id) and self.test_checks[test_id].isChecked()
        ]
        if not disabled_selected:
            QMessageBox.information(self, "Remove Disabled Tests", "No disabled tests are currently selected in the raw preset.")
            return
        for test_id in disabled_selected:
            cb = self.test_checks.get(test_id)
            if cb is not None:
                cb.setEnabled(True)
                cb.setChecked(False)
        self._dirty = True
        self._refresh_preview()
        self._rebuild_test_checkboxes()

    def _accept_auto_fixes(self) -> None:
        pending = self._pending_auto_fix_entries()
        normalized_order = normalize_test_type_list(_parse_str_csv(self.ed_test_order.text()))
        normalized_profile_map = normalize_test_type_map(_parse_json_object(self.ed_profiles_json.toPlainText()))

        changed = False
        if self.ed_test_order.text().strip() != _csv(normalized_order):
            self.ed_test_order.setText(_csv(normalized_order))
            changed = True

        normalized_profiles_text = json.dumps(normalized_profile_map, ensure_ascii=False, indent=2)
        current_profiles_text = json.dumps(_parse_json_object(self.ed_profiles_json.toPlainText()), ensure_ascii=False, indent=2)
        if normalized_profiles_text != current_profiles_text:
            self.ed_profiles_json.setPlainText(normalized_profiles_text)
            changed = True

        if not changed and not pending:
            QMessageBox.information(self, "Accept Auto Fixes", "There are no pending auto-fix items to apply.")
            return

        self._dirty = True
        self._refresh_preview()

    def _review_issues(self) -> None:
        self.tabs.setCurrentWidget(self.tests_tab)
        self.ed_compatibility_issues.setFocus()

    def _rebuild_test_checkboxes(self, selected_tests: list[str] | None = None) -> None:
        preserved = normalize_test_id_list(
            selected_tests if selected_tests is not None else [name for name, cb in self.test_checks.items() if cb.isChecked()]
        )
        temp_model = self._get_model_from_form(selected_tests_override=preserved)
        migration = analyze_preset_model(temp_model, self._load_ruleset_payload(temp_model.ruleset_id))
        pending_auto_fixes = self._pending_auto_fix_entries()
        disabled_reason_map = {
            item.value: item.reason
            for item in migration.disabled_items
            if item.field == "test_types"
        }
        while self.test_checks_layout.count():
            item = self.test_checks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        payload = self._load_ruleset_payload(self.cb_ruleset.currentText().strip())
        catalog = self._ruleset_test_catalog(payload, self.cb_band.currentText().strip(), preserved)
        self.test_checks = {}
        self._test_checkbox_state = {}
        display_order = list(catalog["available"]) + [test_id for test_id in catalog["invalid_selected"] if test_id not in catalog["available"]]
        for idx, test_id in enumerate(display_order):
            description = str(catalog["descriptions"].get(test_id) or canonical_test_label(test_id))
            is_disabled = test_id in disabled_reason_map
            label = f"{test_id}   {description}"
            if is_disabled:
                label += "   [Disabled]   [Excluded from execution]"
            cb = QCheckBox(label)
            tooltip = str(catalog["tooltips"].get(test_id) or description)
            cb.setChecked(test_id in preserved)
            is_invalid = test_id in catalog["invalid_selected"]
            if is_disabled:
                tooltip += "\nStatus: Disabled in raw preset. Excluded from execution.\nReason: " + disabled_reason_map[test_id]
                cb.setEnabled(False)
                cb.setStyleSheet(
                    "QCheckBox { color: #5f6b7a; font-weight: 500; }"
                    "QCheckBox::indicator { border: 1px solid #98a2b3; }"
                )
            elif is_invalid:
                tooltip += "\nStatus: Preserved in raw preset but not currently executable for the selected RuleSet/band."
                cb.setStyleSheet("color: #8a4b08; font-weight: 600;")
            cb.setToolTip(tooltip)
            if not is_disabled:
                cb.toggled.connect(self._mark_dirty_and_refresh)
            self.test_checks[test_id] = cb
            self._test_checkbox_state[test_id] = {
                "invalid": is_invalid,
                "disabled": is_disabled,
                "disabled_reason": disabled_reason_map.get(test_id, ""),
                "description": description,
                "measurement_class": str(catalog["measurement_classes"].get(test_id) or ""),
                "required_instruments": list(catalog["required_instruments"].get(test_id) or []),
            }
            self.test_checks_layout.addWidget(cb, idx // 3, idx % 3)

        summary_lines = [
            f"Band Allowed: {', '.join(catalog['supported']) if catalog['supported'] else '(none declared)'}",
            f"Ruleset + Pool Selectable: {', '.join(catalog['available']) if catalog['available'] else '(none allowed)'}",
        ]
        if catalog["missing_contracts"]:
            summary_lines.append(f"Missing Contracts: {', '.join(catalog['missing_contracts'])}")
        if catalog["orphan_contracts"]:
            summary_lines.append(f"Orphan Contracts: {', '.join(catalog['orphan_contracts'])}")
        self.lb_test_catalog_summary.setText("\n".join(summary_lines))
        if catalog["invalid_selected"]:
            self.lb_test_catalog_warning.setText(
                "RuleSet mismatch: "
                + ", ".join(catalog["invalid_selected"])
                + " is selected in this raw preset but not currently allowed by the selected RuleSet/band. "
                + "It will stay preserved in the raw preset and be excluded from the effective preset at execution time."
            )
            self.lb_test_catalog_warning.setStyleSheet(
                "background:#fff4e5; border:1px solid #f5c36b; border-radius:6px; padding:8px; color:#8a4b08;"
            )
            self.lb_test_catalog_warning.show()
        else:
            self.lb_test_catalog_warning.setText("")
            self.lb_test_catalog_warning.hide()
        self._refresh_compatibility_ui(migration, pending_auto_fixes=pending_auto_fixes)

    def _refresh_ruleset_summary(self) -> None:
        ruleset_id = self.cb_ruleset.currentText().strip()
        payload = self._load_ruleset_payload(ruleset_id)
        if not payload:
            self.lb_ruleset_summary.setText(
                "Selected RuleSet file could not be loaded. The preset can still be saved, "
                "but band/standard suggestions and policy hints are unavailable."
            )
            return
        case_dimensions = normalize_case_dimensions(payload.get("case_dimensions") or {})
        dimension_names = list((case_dimensions.get("dimensions") or {}).keys())
        optional_axes = [str(item.get("name", "")).strip() for item in (case_dimensions.get("optional_axes") or []) if str(item.get("name", "")).strip()]
        bands = [str(name).strip() for name in dict(payload.get("bands") or {}).keys() if str(name).strip()]
        selected_band = self.cb_band.currentText().strip()
        catalog = self._ruleset_test_catalog(payload, selected_band)
        supported_tests = list(catalog.get("available") or [])
        version = str(payload.get("version", "")).strip() or "(unspecified)"
        self.lb_ruleset_summary.setText(
            "Selected RuleSet applies here.\n"
            f"- ID/Version: {ruleset_id} / {version}\n"
            f"- Bands: {', '.join(bands) if bands else '(none)'}\n"
            f"- Axis Engine: {'axis-aware' if case_dimensions.get('defined') else 'legacy-compatible'}\n"
            f"- Dimensions: {', '.join(dimension_names) if dimension_names else '(none)'}\n"
            f"- Optional Axes: {', '.join(optional_axes) if optional_axes else '(none)'}\n"
            f"- Available Tests (ruleset + pool): {', '.join(supported_tests) if supported_tests else '(none allowed)'}"
        )

    def _on_ruleset_changed(self, _ruleset_id: str) -> None:
        if self._loading_form:
            return
        self._reload_band_options()
        self._reload_standard_options()
        self._rebuild_test_checkboxes()
        self._refresh_ruleset_summary()
        payload = self._load_ruleset_payload(self.cb_ruleset.currentText().strip())
        version = str(payload.get("version", "")).strip()
        if version:
            self.ed_ruleset_version.setText(version)
        self._mark_dirty_and_refresh()

    def _on_band_changed(self, _band: str) -> None:
        if self._loading_form:
            return
        self._reload_standard_options()
        self._rebuild_test_checkboxes()
        self._refresh_ruleset_summary()
        self._mark_dirty_and_refresh()

    def _select_all_available_tests(self) -> None:
        for test_id, cb in self.test_checks.items():
            if self._test_checkbox_state.get(test_id, {}).get("disabled"):
                continue
            cb.setChecked(True)

    def _clear_all_tests(self) -> None:
        for test_id, cb in self.test_checks.items():
            if self._test_checkbox_state.get(test_id, {}).get("disabled"):
                continue
            cb.setChecked(False)

    def _refresh_psd_result_unit_hint(self) -> None:
        band = self.cb_band.currentText().strip()
        ruleset_id = self.cb_ruleset.currentText().strip()
        explicit = str(self.cb_psd_result_unit.currentData() or "").strip()
        effective = resolve_psd_result_unit(
            preset_unit=explicit,
            band=band,
            ruleset_id=ruleset_id,
        )
        if explicit:
            self.lb_psd_result_unit_hint.setText(
                f"Effective PSD display policy: {effective} (preset override)"
            )
        else:
            self.lb_psd_result_unit_hint.setText(
                f"Effective PSD display policy: {effective} (ruleset/band default)"
            )

    def _sanitize_instrument_profile_map(
        self,
        *,
        measurement_profile_name: str,
        selected_tests: list[str],
        raw_map: dict,
    ) -> dict[str, str]:
        normalized_map = normalize_test_type_map(raw_map)
        if not measurement_profile_name:
            return normalized_map

        sanitized: dict[str, str] = {}
        for test_type, profile_name in normalized_map.items():
            normalized_profile_name = normalize_profile_name(profile_name)
            if not normalized_profile_name:
                continue
            if (
                test_type in normalize_test_type_list(selected_tests)
                and normalized_profile_name == default_profile_for_test_type(test_type)
                and normalized_profile_name != measurement_profile_name
            ):
                continue
            sanitized[test_type] = normalized_profile_name
        return sanitized

    def _build_axis_aware_summary(self, model: PresetModel) -> dict:
        ruleset_payload = self._load_ruleset_payload(model.ruleset_id)
        case_dimensions = normalize_case_dimensions((ruleset_payload.get("case_dimensions") or {}) if ruleset_payload else {})
        selection = model.selection
        selected_tests = normalize_test_type_list(selection.test_types)
        standards = self._selected_standards_for_summary(model)
        bandwidths = self._selected_bandwidths_for_summary(model)
        channels = self._selected_channels_for_summary(model)
        data_rate_policy = normalize_data_rate_policy((ruleset_payload.get("data_rate_policy") or {}) if ruleset_payload else {})
        voltage_policy = normalize_voltage_policy((ruleset_payload.get("voltage_policy") or {}) if ruleset_payload else {})
        axis_values = self._build_axis_value_summary(
            case_dimensions=case_dimensions,
            model=model,
            standards=standards,
            bandwidths=bandwidths,
            channels=channels,
            data_rate_policy=data_rate_policy,
            voltage_policy=voltage_policy,
        )
        estimated_case_count = self._estimate_axis_case_count(
            model=model,
            standards=standards,
            bandwidths=bandwidths,
            channels=channels,
            data_rate_policy=data_rate_policy,
            voltage_policy=voltage_policy,
        )
        return {
            "ruleset_id": model.ruleset_id,
            "axis_engine_mode": "axis-aware" if case_dimensions.get("defined") else "legacy-compatible",
            "case_dimensions_defined": bool(case_dimensions.get("defined")),
            "base_axes": list(case_dimensions.get("base") or []),
            "optional_axes": [dict(item) for item in (case_dimensions.get("optional_axes") or [])],
            "dimension_names": list((case_dimensions.get("dimensions") or {}).keys()),
            "selected_test_types": selected_tests,
            "axis_values": axis_values,
            "estimated_case_count_before_overrides": estimated_case_count,
            "measurement_profile_name": self._selected_measurement_profile_name(),
            "measurement_profile_map": self._sanitize_instrument_profile_map(
                measurement_profile_name=self._selected_measurement_profile_name(),
                selected_tests=selected_tests,
                raw_map=_parse_json_object(self.ed_profiles_json.toPlainText()),
            ),
            "psd_result_unit_effective": resolve_psd_result_unit(
                preset_unit=selection.psd_result_unit,
                band=selection.band,
                ruleset_id=model.ruleset_id,
            ),
            "compatibility_note": (
                "Preview is axis-aware, but generated cases still map to existing band/standard/bw/channel fields "
                "so Plan/Results/Compare stay compatible."
            ),
        }

    def _build_axis_value_summary(
        self,
        *,
        case_dimensions: dict,
        model: PresetModel,
        standards: list[str],
        bandwidths: list[int],
        channels: list[int],
        data_rate_policy: dict,
        voltage_policy: dict,
    ) -> dict:
        selection = model.selection
        dimensions = dict(case_dimensions.get("dimensions") or {})
        summary: dict[str, object] = {}
        for axis_name, axis_def in dimensions.items():
            source = str(axis_def.get("source", "") or "")
            maps_to = str(axis_def.get("maps_to", "") or "")
            if axis_name == "frequency_band":
                summary[axis_name] = {
                    "type": axis_def.get("type", ""),
                    "source": source,
                    "maps_to": maps_to,
                    "selected": [selection.band] if selection.band else [],
                }
            elif axis_name == "standard":
                summary[axis_name] = {
                    "type": axis_def.get("type", ""),
                    "source": source,
                    "maps_to": maps_to,
                    "selected": standards,
                }
            elif axis_name == "bandwidth":
                summary[axis_name] = {
                    "type": axis_def.get("type", ""),
                    "source": source,
                    "maps_to": maps_to,
                    "selected": bandwidths,
                }
            elif axis_name == "channel":
                summary[axis_name] = {
                    "type": axis_def.get("type", ""),
                    "source": source,
                    "maps_to": maps_to,
                    "selected": channels,
                    "selection_policy": selection.channels.policy,
                }
            elif axis_name == "data_rate":
                summary[axis_name] = self._build_data_rate_axis_summary(
                    axis_def=axis_def,
                    model=model,
                    standards=standards,
                    data_rate_policy=data_rate_policy,
                )
            elif axis_name == "voltage":
                summary[axis_name] = self._build_voltage_axis_summary(
                    axis_def=axis_def,
                    model=model,
                    voltage_policy=voltage_policy,
                )
            else:
                summary[axis_name] = {
                    "type": axis_def.get("type", ""),
                    "source": source,
                    "maps_to": maps_to,
                    "selected": list(axis_def.get("values") or []),
                }
        return summary

    def _build_data_rate_axis_summary(self, *, axis_def: dict, model: PresetModel, standards: list[str], data_rate_policy: dict) -> dict:
        selected_data_rates = [str(item).strip().upper() for item in (model.selection.selected_data_rates or []) if str(item).strip()]
        allowed_by_standard = {
            standard: list((data_rate_policy.get("by_standard") or {}).get(standard, []))
            for standard in standards
        }
        effective_by_standard = {}
        for standard, allowed in allowed_by_standard.items():
            effective = [rate for rate in allowed if not selected_data_rates or rate in selected_data_rates]
            effective_by_standard[standard] = effective
        applies_to = list(data_rate_policy.get("apply_to") or [])
        selected_tests = normalize_test_type_list(model.selection.test_types)
        active_for_tests = [test for test in selected_tests if not applies_to or test in applies_to]
        return {
            "type": axis_def.get("type", ""),
            "source": axis_def.get("source", ""),
            "maps_to": axis_def.get("maps_to", ""),
            "enabled": bool(data_rate_policy.get("enabled")),
            "apply_to": applies_to,
            "selected_subset": selected_data_rates,
            "allowed_by_standard": allowed_by_standard,
            "effective_by_standard": effective_by_standard,
            "active_for_tests": active_for_tests,
        }

    def _build_voltage_axis_summary(self, *, axis_def: dict, model: PresetModel, voltage_policy: dict) -> dict:
        nominal_voltage_v = model.selection.nominal_voltage_v
        levels = [dict(item) for item in (voltage_policy.get("levels") or [])]
        computed_levels = []
        if nominal_voltage_v not in (None, ""):
            for item in levels:
                try:
                    percent_offset = float(item.get("percent_offset", 0.0))
                except Exception:
                    percent_offset = 0.0
                computed_levels.append(
                    {
                        "name": str(item.get("name", "")).strip().upper(),
                        "label": str(item.get("label", "")).strip(),
                        "target_voltage_v": round(float(nominal_voltage_v) * (1.0 + percent_offset / 100.0), 6),
                    }
                )
        applies_to = list(voltage_policy.get("apply_to") or [])
        selected_tests = normalize_test_type_list(model.selection.test_types)
        active_for_tests = [test for test in selected_tests if not applies_to or test in applies_to]
        return {
            "type": axis_def.get("type", ""),
            "source": axis_def.get("source", ""),
            "maps_to": axis_def.get("maps_to", ""),
            "enabled": bool(voltage_policy.get("enabled")),
            "apply_to": applies_to,
            "nominal_voltage_v": nominal_voltage_v,
            "defined_levels": levels,
            "computed_levels": computed_levels,
            "active_for_tests": active_for_tests,
        }

    def _estimate_axis_case_count(
        self,
        *,
        model: PresetModel,
        standards: list[str],
        bandwidths: list[int],
        channels: list[int],
        data_rate_policy: dict,
        voltage_policy: dict,
    ) -> int:
        selected_tests = normalize_test_type_list(model.selection.test_types)
        total = 0
        applies_data_rate = list(data_rate_policy.get("apply_to") or [])
        applies_voltage = list(voltage_policy.get("apply_to") or [])
        voltage_levels = list(voltage_policy.get("levels") or [])
        selected_data_rates = [str(item).strip().upper() for item in (model.selection.selected_data_rates or []) if str(item).strip()]

        builder = self._current_plan_builder(model)
        if builder is not None:
            try:
                return len(builder.build_steps(model))
            except Exception:
                pass

        standard_values = standards or [""]
        bw_count = max(len(bandwidths), 1)
        channel_count = max(len(channels), 1)
        for test_type in selected_tests:
            for standard in standard_values:
                rate_multiplier = 1
                if bool(data_rate_policy.get("enabled")) and (not applies_data_rate or test_type in applies_data_rate):
                    allowed = list((data_rate_policy.get("by_standard") or {}).get(standard, []))
                    effective = [rate for rate in allowed if not selected_data_rates or rate in selected_data_rates]
                    rate_multiplier = max(len(effective), 1)
                voltage_multiplier = 1
                if (
                    bool(voltage_policy.get("enabled"))
                    and model.selection.nominal_voltage_v not in (None, "")
                    and voltage_levels
                    and (not applies_voltage or test_type in applies_voltage)
                ):
                    voltage_multiplier = len(voltage_levels)
                total += bw_count * channel_count * rate_multiplier * voltage_multiplier
        return total

    def _selected_standards_for_summary(self, model: PresetModel) -> list[str]:
        if self._is_wlan_selected() and model.selection.wlan_expansion:
            out: list[str] = []
            for row in model.selection.wlan_expansion.mode_plan:
                standard = str(row.standard).strip()
                if standard and standard not in out:
                    out.append(standard)
            if out:
                return out
        standard = str(model.selection.standard or "").strip()
        return [standard] if standard else []

    def _selected_bandwidths_for_summary(self, model: PresetModel) -> list[int]:
        if self._is_wlan_selected() and model.selection.wlan_expansion:
            out: list[int] = []
            for row in model.selection.wlan_expansion.channel_plan:
                value = int(row.bandwidth_mhz)
                if value not in out:
                    out.append(value)
            if out:
                return sorted(out)
        return sorted({int(value) for value in (model.selection.bandwidth_mhz or [])})

    def _selected_channels_for_summary(self, model: PresetModel) -> list[int]:
        if self._is_wlan_selected() and model.selection.wlan_expansion:
            out: list[int] = []
            for row in model.selection.wlan_expansion.channel_plan:
                for ch in row.channels:
                    value = int(ch)
                    if value not in out:
                        out.append(value)
            if out:
                return sorted(out)
        return sorted({int(value) for value in (model.selection.channels.channels or [])})

    def _load_ruleset_payload(self, ruleset_id: str) -> dict:
        normalized = str(ruleset_id or "").strip()
        if not normalized:
            return {}
        path = Path("rulesets") / f"{normalized.lower()}.json"
        if not path.exists() and normalized.upper() == "KC_WLAN":
            alt = Path("rulesets") / "kc_wlan.json"
            if alt.exists():
                path = alt
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["test_contracts"] = project_ruleset_test_contracts(
                payload.get("test_contracts") or {},
                tests_supported=collect_ruleset_test_types(payload),
            )
            return payload
        except Exception:
            return {}


def _sync_selection_summary_from_wlan_expansion(model: PresetModel) -> None:
    wlan = model.selection.wlan_expansion
    if wlan is None:
        return

    standards: list[str] = []
    bandwidths: list[int] = []
    channels: list[int] = []

    for row in wlan.mode_plan:
        standard = str(row.standard).strip()
        if standard and standard not in standards:
            standards.append(standard)
        for bw in row.bandwidths_mhz:
            ibw = int(bw)
            if ibw not in bandwidths:
                bandwidths.append(ibw)

    for row in wlan.channel_plan:
        if int(row.bandwidth_mhz) not in bandwidths:
            bandwidths.append(int(row.bandwidth_mhz))
        for ch in row.channels:
            ich = int(ch)
            if ich not in channels:
                channels.append(ich)

    model.selection.standard = standards[0] if len(standards) == 1 else ""
    model.selection.bandwidth_mhz = sorted(bandwidths)
    model.selection.channels = ChannelSelectionModel(policy="CUSTOM_LIST", channels=sorted(channels))


def _parse_int_csv(text: str) -> list[int]:
    out = []
    for part in _parse_str_csv(text):
        try:
            out.append(int(part))
        except Exception:
            continue
    return out


def _parse_str_csv(text: str) -> list[str]:
    return [p.strip() for p in str(text).split(",") if p.strip()]


def _csv(values: list[object]) -> str:
    return ", ".join(str(v) for v in values)


def _parse_json_object(text: str) -> dict:
    raw = str(text).strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _slugify(name: str) -> str:
    safe = []
    for ch in name.strip():
        if ch.isalnum():
            safe.append(ch.lower())
        elif ch in ("-", "_"):
            safe.append(ch)
        else:
            safe.append("_")
    slug = "".join(safe).strip("_")
    return slug or "preset"
