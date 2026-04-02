from __future__ import annotations

import json
from pathlib import Path

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
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from application.migrations_preset import migrate_preset_to_latest
from application.measurement_profile_loader import MeasurementProfileLoader
from application.plan_builders.wlan_plan_builder import WlanPlanBuilder
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
from application.psd_unit_policy import (
    PSD_UNIT_DBM_PER_MHZ,
    PSD_UNIT_MW_PER_MHZ,
    resolve_psd_result_unit,
)
from application.preset_validator import PresetValidator
from application.test_type_symbols import DEFAULT_TEST_ORDER, PLAN_FILTER_TEST_TYPES, default_profile_for_test_type, normalize_profile_name, normalize_test_type_list, normalize_test_type_map
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
        self._wlan_builder = WlanPlanBuilder()
        self.last_imported_project_preset_id: str | None = None
        self.last_imported_project_preset_name: str | None = None
        self.last_saved_preset_path: str | None = None

        self.setWindowTitle("Preset Editor")
        self.resize(1180, 760)
        self._build_ui()
        self._load_preset_list()
        self._new_preset()

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
        self.cb_ruleset.currentTextChanged.connect(self._update_expansion_visibility)
        self.cb_standard.currentTextChanged.connect(self._update_expansion_visibility)
        self.cb_ruleset.currentTextChanged.connect(self._refresh_psd_result_unit_hint)
        self.cb_band.currentTextChanged.connect(self._refresh_psd_result_unit_hint)
        self.cb_psd_result_unit.currentTextChanged.connect(self._refresh_psd_result_unit_hint)
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
        form = QFormLayout(tab)
        self.ed_name = QLineEdit()
        self.ed_description = QTextEdit()
        self.ed_description.setFixedHeight(80)
        self.cb_ruleset = QComboBox(); self.cb_ruleset.setEditable(True)
        self.cb_ruleset.addItems(["KC_WLAN", "FCC_WLAN", "ETSI_WLAN", "KC_BT", "CUSTOM"])
        self.ed_ruleset_version = QLineEdit("2026.02")
        self.cb_band = QComboBox(); self.cb_band.setEditable(True)
        self.cb_band.addItems(["2.4G", "5G", "6G"])
        self.lb_standard = QLabel("Standard")
        self.cb_standard = QComboBox(); self.cb_standard.setEditable(True)
        self.cb_standard.addItems(["802.11b", "802.11g", "802.11n", "802.11ac", "802.11ax", "BT LE"])
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
        form.addRow("Name", self.ed_name)
        form.addRow("Description", self.ed_description)
        form.addRow("RuleSet ID", self.cb_ruleset)
        form.addRow("RuleSet Version", self.ed_ruleset_version)
        form.addRow("Band", self.cb_band)
        form.addRow(self.lb_standard, self.cb_standard)
        form.addRow("Plan Mode", self.cb_plan_mode)
        form.addRow("Measurement Profile", self.cb_measurement_profile)
        form.addRow("PSD Result Unit", self.cb_psd_result_unit)
        form.addRow("", self.lb_psd_result_unit_hint)
        form.addRow("Nominal Voltage", self.sp_nominal_voltage)
        form.addRow("Device Class", self.ed_device_class)
        self._reload_measurement_profile_options()
        self._refresh_psd_result_unit_hint()
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
        self.wlan_editor = WlanExpansionEditor(self.wlan_tab)
        layout.addWidget(self.wlan_editor)
        self.tabs.addTab(self.wlan_tab, "WLAN Expansion")

    def _build_tests_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        help_label = QLabel("Select test items included in the preset. Execution order is configured below in Execution Policy.")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        grid = QGridLayout()
        self.test_checks: dict[str, QCheckBox] = {}
        test_items = [
            *PLAN_FILTER_TEST_TYPES,
            "BANDEDGE", "COND_POWER", "ACP", "ACLR", "RX_BLOCKING"
        ]
        for idx, test_name in enumerate(test_items):
            cb = QCheckBox(test_name)
            self.test_checks[test_name] = cb
            grid.addWidget(cb, idx // 3, idx % 3)
        layout.addLayout(grid)

        profiles_grp = QGroupBox("Instrument Profiles")
        profiles_form = QFormLayout(profiles_grp)
        self.ed_profiles_json = QPlainTextEdit(); self.ed_profiles_json.setFixedHeight(120)
        self.ed_profiles_json.setPlaceholderText('{\n  "PSD": "PSD_DEFAULT"\n}')
        profiles_form.addRow("Profiles JSON", self.ed_profiles_json)
        layout.addWidget(profiles_grp)

        exec_grp = QGroupBox("Execution Policy")
        exec_form = QFormLayout(exec_grp)
        self.cb_exec_type = QComboBox(); self.cb_exec_type.addItems(["CHANNEL_CENTRIC", "TEST_CENTRIC"])
        self.ed_test_order = QLineEdit(",".join(DEFAULT_TEST_ORDER))
        self.chk_include_bw = QCheckBox("Include BW in Group"); self.chk_include_bw.setChecked(True)
        exec_form.addRow("Type", self.cb_exec_type)
        exec_form.addRow("Test Order (CSV)", self.ed_test_order)
        exec_form.addRow("", self.chk_include_bw)
        layout.addWidget(exec_grp)

        layout.addStretch(1)
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
                test_types=["PSD", "OBW", "SP", "RX"],
                execution_policy=ExecutionPolicyModel(type="CHANNEL_CENTRIC", test_order=["PSD", "OBW", "SP", "RX"], include_bw_in_group=True),
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
            self.cb_ruleset.setCurrentText(model.ruleset_id)
            self.ed_ruleset_version.setText(model.ruleset_version)
            self.cb_band.setCurrentText(sel.band)
            self.cb_standard.setCurrentText(sel.standard)
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
            selected_test_types = set(normalize_test_type_list(sel.test_types))
            for test_name, cb in self.test_checks.items():
                cb.setChecked(test_name in selected_test_types)
            self._update_expansion_visibility()
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

    def _get_model_from_form(self) -> PresetModel:
        selected_tests = [name for name, cb in self.test_checks.items() if cb.isChecked()]
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

            sections: list[str] = []
            sections.append("# VALIDATION\n" + validation.summary())

            if self._is_wlan_selected():
                steps = self._wlan_builder.build_steps(model)
                sample = steps[:12]
                explanation = (
                    "WLAN Expansion works like this:\n"
                    "- Mode Plan chooses standard / phy mode / bandwidth\n"
                    "- Channel Plan chooses channels for each bandwidth\n"
                    "- Selected test items are multiplied into final execution steps"
                )
                sections.append(
                    "# WLAN PLAN PREVIEW\n"
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
            self.preview.setPlainText(f"<preview unavailable>\n{e}")

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
            self.cb_standard.setToolTip("")
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
