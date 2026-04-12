from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.ruleset_templates import get_available_templates, load_template
from domain.ruleset_models import (
    build_test_contract_projection,
    collect_ruleset_test_types,
    project_ruleset_test_contracts,
    normalize_case_dimensions,
    normalize_data_rate_policy,
    normalize_psd_policy,
    normalize_voltage_policy,
    validate_ruleset_payload,
)
from domain.test_item_pool import get_test_item_definition, list_available_test_items
from domain.test_item_registry import canonical_test_label, normalize_test_id, normalize_test_id_list


KNOWN_TEST_TYPES = tuple(item["id"] for item in list_available_test_items(selectable_only=True))
PSD_METHODS = ("MARKER_PEAK", "AVERAGE")
PSD_UNITS = ("MW_PER_MHZ", "DBM_PER_MHZ")
PSD_COMPARATORS = ("upper_limit", "lower_limit")
VERDICT_TYPES = ("limit_upper", "limit_lower", "range", "custom")
PREVIEW_RENDER_LIMIT = 500
PREVIEW_GENERATION_LIMIT = 5000


class CreateRulesetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Ruleset")
        self.resize(420, 180)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose a template to start a new ruleset."))
        self.cb_template = QComboBox()
        for item in get_available_templates():
            self.cb_template.addItem(item["label"], item["id"])
        layout.addWidget(self.cb_template)
        self.lb_help = QLabel(
            "WLAN template includes KC WLAN defaults.\n"
            "Minimal starts with the smallest runnable policy set.\n"
            "Custom creates an empty editor-friendly skeleton."
        )
        self.lb_help.setWordWrap(True)
        layout.addWidget(self.lb_help)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_template_id(self) -> str:
        return str(self.cb_template.currentData() or "CUSTOM_EMPTY")


class AddTestItemFromPoolDialog(QDialog):
    def __init__(
        self,
        *,
        ruleset_tech: str,
        available_items: List[Dict[str, Any]],
        bands: List[str],
        preselected_band: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._available_items = list(available_items)
        self._row_lookup: list[tuple[QListWidgetItem, dict[str, Any]]] = []
        self._band_checks: Dict[str, QCheckBox] = {}
        self.setWindowTitle("Add Test Item from Pool")
        self.resize(760, 520)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Select executable test items from the global pool.\n"
            f"RuleSet tech: {ruleset_tech or '(empty)'}"
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter"))
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText("Search by ID, display name, measurement class, instrument, or axis")
        filter_row.addWidget(self.ed_filter, 1)
        root.addLayout(filter_row)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Available Test Items"))
        self.list_items = QListWidget()
        self.list_items.setSelectionMode(QListWidget.MultiSelection)
        left_layout.addWidget(self.list_items, 1)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Apply To Bands"))
        self.chk_all_bands = QCheckBox("All bands")
        self.chk_all_bands.setChecked(True)
        right_layout.addWidget(self.chk_all_bands)
        for band_name in bands:
            checkbox = QCheckBox(band_name)
            checkbox.setChecked(True if not preselected_band else band_name == preselected_band)
            right_layout.addWidget(checkbox)
            self._band_checks[band_name] = checkbox
        right_layout.addStretch(1)
        self.lb_help = QLabel(
            "Only selectable pool items are shown.\n"
            "Already-added test items are excluded.\n"
            "Canonical IDs only will be stored."
        )
        self.lb_help.setWordWrap(True)
        right_layout.addWidget(self.lb_help)
        split.addWidget(right)
        split.setSizes([560, 200])

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Add Selected")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.ed_filter.textChanged.connect(self._apply_filter)
        self.chk_all_bands.toggled.connect(self._on_all_bands_toggled)
        for checkbox in self._band_checks.values():
            checkbox.toggled.connect(self._sync_all_bands_state)

        self._populate_items()

    def _populate_items(self) -> None:
        self.list_items.clear()
        self._row_lookup = []
        for payload in self._available_items:
            item_id = str(payload.get("id", "")).strip()
            title = f"{item_id}    {payload.get('display_name', item_id)}"
            subtitle = (
                f"class={payload.get('measurement_class', '')} | "
                f"instruments={', '.join(payload.get('required_instruments') or []) or '(none)'} | "
                f"techs={', '.join(payload.get('supported_techs') or []) or '(all)'} | "
                f"axes={', '.join(payload.get('supported_axes') or []) or '(none)'}"
            )
            row = QListWidgetItem(f"{title}\n{subtitle}")
            row.setData(Qt.UserRole, item_id)
            row.setToolTip(subtitle)
            self.list_items.addItem(row)
            self._row_lookup.append((row, payload))
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.ed_filter.text().strip().lower()
        for row, payload in self._row_lookup:
            hay = " ".join(
                [
                    str(payload.get("id", "")),
                    str(payload.get("display_name", "")),
                    str(payload.get("measurement_class", "")),
                    " ".join(str(item) for item in (payload.get("required_instruments") or [])),
                    " ".join(str(item) for item in (payload.get("supported_techs") or [])),
                    " ".join(str(item) for item in (payload.get("supported_axes") or [])),
                ]
            ).lower()
            row.setHidden(bool(needle) and needle not in hay)

    def _on_all_bands_toggled(self, checked: bool) -> None:
        for checkbox in self._band_checks.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

    def _sync_all_bands_state(self, _checked: bool) -> None:
        if not self._band_checks:
            self.chk_all_bands.setChecked(False)
            return
        all_checked = all(checkbox.isChecked() for checkbox in self._band_checks.values())
        self.chk_all_bands.blockSignals(True)
        self.chk_all_bands.setChecked(all_checked)
        self.chk_all_bands.blockSignals(False)

    def selected_test_ids(self) -> List[str]:
        out: List[str] = []
        for row in self.list_items.selectedItems():
            value = str(row.data(Qt.UserRole) or "").strip()
            if value and value not in out:
                out.append(value)
        return out

    def selected_bands(self) -> List[str]:
        out: List[str] = []
        for band_name, checkbox in self._band_checks.items():
            if checkbox.isChecked():
                out.append(band_name)
        return out


class RulesetAxisEditorDialog(QDialog):
    SECTION_TABS = (
        "General",
        "Case Dimensions",
        "PSD Policy",
        "Voltage Policy",
        "Data Rate Policy",
        "Test Contracts",
        "Validation",
    )

    def __init__(self, ruleset_data: Dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self._ruleset_data: Dict[str, Any] = dict(ruleset_data or {})
        self._current_path: str = ""
        self._loading = False
        self._preview_rows: List[Dict[str, Any]] = []
        self._preview_analysis: Dict[str, Any] = {}
        self._ui_mode: str = "basic"
        self._updating_voltage_labels = False
        self._applying_visual_polish = False
        self._validation_styled_widgets: List[QWidget] = []
        self._help_banners: List[QLabel] = []
        self._card_frames: List[QFrame] = []
        self._card_title_labels: List[QLabel] = []
        self._card_subtitle_labels: List[QLabel] = []
        self.setWindowTitle("Ruleset Axis Editor")
        self._build_ui()
        self._apply_dialog_geometry()
        self._apply_visual_polish()
        if self._ruleset_data:
            self.load_ruleset_data(self._ruleset_data)
        else:
            self.on_new_clicked(initial=True)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(QLabel("Mode"))
        self.cb_ui_mode = QComboBox()
        self.cb_ui_mode.addItem("Basic Mode", "basic")
        self.cb_ui_mode.addItem("Advanced Mode", "advanced")
        self.cb_ui_mode.setMinimumWidth(150)
        top_row.addWidget(self.cb_ui_mode)
        top_row.addStretch(1)
        root.addLayout(top_row)
        root.addWidget(self._make_help_banner(
            "Ruleset defines policy. Preset selects scope.\n"
            "Use this editor to define case axes, measurement policy, and execution contracts.\n"
            "At runtime, measurement profiles win over ruleset instrument snapshot fallback."
        ))
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.main_splitter = splitter
        root.addWidget(splitter, 1)

        nav = QWidget()
        nav.setMinimumWidth(180)
        nav_layout = QVBoxLayout(nav)
        nav_layout.addWidget(QLabel("Editor Sections"))
        self.section_list = QListWidget()
        for name in self.SECTION_TABS:
            self.section_list.addItem(name)
        nav_layout.addWidget(self.section_list, 1)
        splitter.addWidget(nav)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        self.tabs = QTabWidget()
        body_layout.addWidget(self.tabs, 1)
        splitter.addWidget(body)
        splitter.setSizes([200, 920])

        self._build_general_tab()
        self._build_case_dimensions_tab()
        self._build_psd_policy_tab()
        self._build_voltage_tab()
        self._build_data_rate_tab()
        self._build_test_contracts_tab()
        self._build_validation_tab()

        actions = QHBoxLayout()
        self.btn_new = QPushButton("New")
        self.btn_load = QPushButton("Load")
        self.btn_save = QPushButton("Save")
        self.btn_save_as = QPushButton("Save As")
        self.btn_clone = QPushButton("Clone")
        self.btn_validate = QPushButton("Validate")
        self.btn_preview_cases = QPushButton("Preview Cases")
        self.btn_close = QPushButton("Close")
        actions.addWidget(self.btn_new)
        actions.addWidget(self.btn_load)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_save_as)
        actions.addWidget(self.btn_clone)
        actions.addStretch(1)
        actions.addWidget(self.btn_validate)
        actions.addWidget(self.btn_preview_cases)
        actions.addWidget(self.btn_close)
        root.addLayout(actions)

        self.section_list.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.section_list.setCurrentRow)
        self.dimension_list.currentItemChanged.connect(self._on_dimension_item_changed)
        self.band_list.currentItemChanged.connect(self._on_band_item_changed)
        self.rate_standard_list.currentItemChanged.connect(self._on_rate_standard_item_changed)
        self.contract_list.currentItemChanged.connect(self._on_contract_item_changed)

        self.btn_load.clicked.connect(self.on_load_clicked)
        self.btn_new.clicked.connect(self.on_new_clicked)
        self.btn_save.clicked.connect(self.on_save_clicked)
        self.btn_save_as.clicked.connect(self.on_save_as_clicked)
        self.btn_clone.clicked.connect(self.on_clone_clicked)
        self.btn_validate.clicked.connect(self.on_validate_clicked)
        self.btn_preview_cases.clicked.connect(self.on_preview_cases_clicked)
        self.btn_close.clicked.connect(self.accept)
        self.cb_preview_test_filter.currentTextChanged.connect(self._apply_preview_filters)
        self.cb_preview_axis_filter.currentTextChanged.connect(self._apply_preview_filters)
        self.chk_preview_expanded_only.toggled.connect(self._apply_preview_filters)

        self.btn_dimension_add.clicked.connect(self.on_add_dimension)
        self.btn_dimension_remove.clicked.connect(self.on_remove_dimension)
        self.btn_dimension_value_add.clicked.connect(lambda: self._append_empty_row(self.dimension_values_table))
        self.btn_dimension_value_remove.clicked.connect(lambda: self._remove_selected_rows(self.dimension_values_table))
        self.btn_voltage_level_add.clicked.connect(lambda: self._append_empty_row(self.voltage_levels_table))
        self.btn_voltage_level_remove.clicked.connect(lambda: self._remove_selected_rows(self.voltage_levels_table))
        self.voltage_levels_table.itemChanged.connect(self._on_voltage_level_item_changed)
        self.btn_rate_standard_add.clicked.connect(self.on_add_standard_rates)
        self.btn_rate_standard_remove.clicked.connect(self.on_remove_standard_rates)
        self.btn_contract_add.clicked.connect(self.on_add_contract)
        self.btn_contract_remove.clicked.connect(self.on_remove_contract)
        self.cb_ui_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.validation_list.itemClicked.connect(self._on_validation_item_clicked)
        self._connect_live_feedback_signals()
        self._configure_combo_boxes(self)
        self.section_list.setCurrentRow(0)

    def _build_general_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.addWidget(self._make_help_banner(
            "General identifies the ruleset itself.\n"
            "This metadata tells the framework which regulation and technology policy set is being edited."
        ))
        form = QFormLayout()
        self.ed_ruleset_id = QLineEdit()
        self.ed_ruleset_version = QLineEdit()
        self.ed_regulation = QLineEdit()
        self.ed_tech = QLineEdit()
        self.ed_schema_version = QLineEdit()
        self.lb_source_path = QLabel("(unsaved)")
        self.lb_source_path.setWordWrap(True)
        form.addRow("RuleSet ID", self.ed_ruleset_id)
        form.addRow("Version", self.ed_ruleset_version)
        form.addRow("Regulation", self.ed_regulation)
        form.addRow("Tech", self.ed_tech)
        form.addRow("Schema Version", self.ed_schema_version)
        form.addRow("Source Path", self.lb_source_path)
        layout.addLayout(form)
        self.ed_ruleset_id.setToolTip("Stable ruleset identifier used by presets and runtime loading.")
        self.ed_ruleset_version.setToolTip("Ruleset revision string. Increase when policy content changes.")
        self.ed_regulation.setToolTip("Regulatory domain, for example KC, CE, or FCC.")
        self.ed_tech.setToolTip("Technology family such as WLAN, LTE, NR, or UWB.")
        self.ed_schema_version.setToolTip("Schema version for editor/runtime compatibility.")
        self.tabs.addTab(self._wrap_tab_page(tab), self.SECTION_TABS[0])

    def _build_case_dimensions_tab(self) -> None:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setSpacing(12)
        outer.addWidget(self._make_help_banner(
            "Case = base axes + optional axes.\n"
            "Base axes shape case identity. Optional axes expand only when their apply_to and policy rules allow it."
        ))
        self.basic_axis_widget = QWidget()
        basic_root = QHBoxLayout(self.basic_axis_widget)
        basic_root.setContentsMargins(0, 0, 0, 0)
        basic_root.setSpacing(18)

        basic_left = QWidget()
        basic_left_layout = QVBoxLayout(basic_left)
        basic_left_layout.setContentsMargins(0, 0, 0, 0)
        basic_left_layout.setSpacing(14)

        test_card, test_layout = self._make_card(
            "Test Setup",
            "Choose the primary test conditions. These controls narrow the live preview without exposing JSON structure.",
        )
        self.cb_basic_standard = QComboBox()
        self.cb_basic_band = QComboBox()
        self.cb_basic_channel_group = QComboBox()
        self.cb_basic_standard.setMinimumWidth(180)
        self.cb_basic_band.setMinimumWidth(120)
        self.cb_basic_channel_group.setMinimumWidth(180)
        test_form = QFormLayout()
        test_form.addRow("Standard", self.cb_basic_standard)
        test_form.addRow("Band", self.cb_basic_band)
        test_form.addRow("Channel Group", self.cb_basic_channel_group)
        test_layout.addLayout(test_form)
        basic_left_layout.addWidget(test_card)

        axis_card, axis_layout = self._make_card(
            "Axis Options",
            "Turn optional case expansion on or off. Basic Mode keeps this to a few safe choices.",
        )
        self.chk_basic_data_rate = QCheckBox("Data Rate")
        self.chk_basic_data_rate.setToolTip("Standard별 전송 속도에 따라 case를 확장합니다.")
        self.chk_basic_voltage = QCheckBox("Voltage")
        self.chk_basic_voltage.setToolTip("정격 / ±10% 전압 조건을 추가합니다.")
        self.chk_basic_temperature = QCheckBox("Temperature")
        self.chk_basic_temperature.setToolTip("향후 온도 축 확장용 기본 enum axis를 생성합니다.")
        self.chk_basic_power_mode = QCheckBox("Power Mode")
        self.chk_basic_power_mode.setToolTip("향후 전력 모드 축 확장용 기본 enum axis를 생성합니다.")
        for widget in (
            self.chk_basic_data_rate,
            self.chk_basic_voltage,
            self.chk_basic_temperature,
            self.chk_basic_power_mode,
        ):
            axis_layout.addWidget(widget)
        self.chk_basic_data_rate.setToolTip("Expand sample cases by standard-specific data rates.")
        self.chk_basic_voltage.setToolTip("Add nominal and plus/minus voltage conditions.")
        self.chk_basic_temperature.setToolTip("Create a simple temperature axis with safe defaults.")
        self.chk_basic_power_mode.setToolTip("Create a simple power mode axis with safe defaults.")
        basic_left_layout.addWidget(axis_card)

        voltage_card, voltage_layout = self._make_card(
            "Voltage Conditions",
            "Choose which voltage levels are included when Voltage is enabled.",
        )
        self.chk_basic_voltage_nominal = QCheckBox("Nominal")
        self.chk_basic_voltage_high = QCheckBox("High (+10%)")
        self.chk_basic_voltage_low = QCheckBox("Low (-10%)")
        voltage_layout.addWidget(self.chk_basic_voltage_nominal)
        voltage_layout.addWidget(self.chk_basic_voltage_high)
        voltage_layout.addWidget(self.chk_basic_voltage_low)
        self.basic_voltage_card = voltage_card
        basic_left_layout.addWidget(voltage_card)

        apply_card, apply_layout = self._make_card(
            "Apply To",
            "Select which test items should use optional axis expansion in Basic Mode.",
        )
        self.basic_apply_to_checks = self._build_test_type_checkboxes()
        apply_layout.addWidget(self._wrap_checkbox_grid("", self.basic_apply_to_checks))
        basic_left_layout.addWidget(apply_card)
        basic_left_layout.addStretch(1)

        basic_right = QWidget()
        basic_right_layout = QVBoxLayout(basic_right)
        basic_right_layout.setContentsMargins(0, 0, 0, 0)
        basic_right_layout.setSpacing(14)

        summary_card, summary_layout = self._make_card(
            "Case Summary",
            "Preview updates immediately so the operator can understand the impact of each checkbox.",
        )
        self.lb_basic_base_cases = QLabel("Base Cases: 0")
        self.lb_basic_data_rate_multiplier = QLabel("Data Rate Multiplier: x1")
        self.lb_basic_voltage_multiplier = QLabel("Voltage Multiplier: x1")
        self.lb_basic_total_cases = QLabel("Total Cases: 0")
        for widget in (
            self.lb_basic_base_cases,
            self.lb_basic_data_rate_multiplier,
            self.lb_basic_voltage_multiplier,
            self.lb_basic_total_cases,
        ):
            widget.setStyleSheet("font-size: 14px; color: #1f2937;")
            summary_layout.addWidget(widget)
        basic_right_layout.addWidget(summary_card)

        sample_card, sample_layout = self._make_card(
            "Sample Cases",
            "Representative rows generated from the current basic-mode selections.",
        )
        self.basic_sample_table = QTableWidget(0, 5)
        self.basic_sample_table.setHorizontalHeaderLabels(["Standard", "Band", "Channel", "Data Rate", "Voltage"])
        self.basic_sample_table.horizontalHeader().setStretchLastSection(True)
        sample_layout.addWidget(self.basic_sample_table, 1)
        basic_right_layout.addWidget(sample_card, 1)

        validation_card, validation_layout = self._make_card(
            "Validation",
            "Warnings and errors appear as you edit. Click a message to jump to the related field.",
        )
        self.basic_validation_list = QListWidget()
        self.basic_validation_list.itemClicked.connect(self._on_validation_item_clicked)
        validation_layout.addWidget(self.basic_validation_list)
        basic_right_layout.addWidget(validation_card)

        basic_root.addWidget(basic_left, 0)
        basic_root.addWidget(basic_right, 1)
        outer.addWidget(self.basic_axis_widget, 1)

        self.advanced_axis_widget = QWidget()
        layout = QHBoxLayout(self.advanced_axis_widget)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Dimensions"))
        self.dimension_list = QListWidget()
        left_layout.addWidget(self.dimension_list, 1)
        row = QHBoxLayout()
        self.btn_dimension_add = QPushButton("Add")
        self.btn_dimension_remove = QPushButton("Remove")
        row.addWidget(self.btn_dimension_add)
        row.addWidget(self.btn_dimension_remove)
        left_layout.addLayout(row)
        layout.addWidget(left, 0)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        form = QFormLayout()
        self.ed_dimension_name = QLineEdit()
        self.cb_dimension_type = QComboBox()
        self.cb_dimension_type.addItems(["enum", "numeric", "computed", "string"])
        self.ed_dimension_source = QLineEdit()
        self.ed_dimension_maps_to = QLineEdit()
        self.chk_dimension_optional = QCheckBox("Optional axis")
        self.dimension_apply_to_checks = self._build_test_type_checkboxes()
        self.cb_dimension_non_applicable_mode = QComboBox()
        self.cb_dimension_non_applicable_mode.addItems(["OMIT", "SINGLE_DEFAULT", "EMPTY_VALUE"])
        form.addRow("Name", self.ed_dimension_name)
        form.addRow("Type", self.cb_dimension_type)
        form.addRow("Source", self.ed_dimension_source)
        form.addRow("Maps To", self.ed_dimension_maps_to)
        form.addRow("", self.chk_dimension_optional)
        form.addRow("Apply To", self._wrap_checkbox_grid("", self.dimension_apply_to_checks))
        form.addRow("Non Applicable Mode", self.cb_dimension_non_applicable_mode)
        right_layout.addLayout(form)
        right_layout.addWidget(QLabel("Enum Values / Fixed Values"))
        self.dimension_values_table = QTableWidget(0, 1)
        self.dimension_values_table.setHorizontalHeaderLabels(["Value"])
        self.dimension_values_table.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self.dimension_values_table, 1)
        row2 = QHBoxLayout()
        self.btn_dimension_value_add = QPushButton("Add Value")
        self.btn_dimension_value_remove = QPushButton("Remove Value")
        row2.addWidget(self.btn_dimension_value_add)
        row2.addWidget(self.btn_dimension_value_remove)
        row2.addStretch(1)
        right_layout.addLayout(row2)
        layout.addWidget(right, 1)
        outer.addLayout(layout, 1)
        self.ed_dimension_name.setToolTip("Axis name stored in case_dimensions. Keep names stable once used in production.")
        self.cb_dimension_type.setToolTip("enum = fixed choices, numeric = numbers, computed = policy-derived, string = free text.")
        self.ed_dimension_source.setToolTip("Where axis values come from, for example bands, channel_groups, data_rate_policy, or voltage_policy.")
        self.ed_dimension_maps_to.setToolTip("Legacy/runtime field mapping such as band, standard, bw_mhz, channel, or tags.data_rate.")
        self.chk_dimension_optional.setToolTip("Optional axes expand only when they resolve values for the current test.")
        self.cb_dimension_non_applicable_mode.setToolTip("How to behave when the current test does not use this axis.")
        outer.addWidget(self.advanced_axis_widget, 1)
        self.tabs.addTab(self._wrap_tab_page(tab), self.SECTION_TABS[1])

    def _build_psd_policy_tab(self) -> None:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setSpacing(10)
        outer.addWidget(self._make_help_banner(
            "PSD policy is edited per band.\n"
            "band.psd_policy is the canonical source of truth. Legacy psd fields remain only for backward compatibility."
        ))
        layout = QHBoxLayout()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Bands"))
        self.band_list = QListWidget()
        left_layout.addWidget(self.band_list, 1)
        layout.addWidget(left, 0)
        right = QWidget()
        form = QFormLayout(right)
        self.cb_psd_method = QComboBox()
        self.cb_psd_method.addItems(list(PSD_METHODS))
        self.cb_psd_result_unit = QComboBox()
        self.cb_psd_result_unit.addItems(list(PSD_UNITS))
        self.cb_psd_comparator = QComboBox()
        self.cb_psd_comparator.addItems(list(PSD_COMPARATORS))
        self.ed_psd_limit_value = QLineEdit()
        self.cb_psd_limit_unit = QComboBox()
        self.cb_psd_limit_unit.addItems(list(PSD_UNITS))
        self.lb_psd_legacy_note = QLabel("")
        self.lb_psd_legacy_note.setWordWrap(True)
        form.addRow("Method", self.cb_psd_method)
        form.addRow("Result Unit", self.cb_psd_result_unit)
        form.addRow("Comparator", self.cb_psd_comparator)
        form.addRow("Limit Value", self.ed_psd_limit_value)
        form.addRow("Limit Unit", self.cb_psd_limit_unit)
        form.addRow("Legacy State", self.lb_psd_legacy_note)
        layout.addWidget(right, 1)
        outer.addLayout(layout, 1)
        self.cb_psd_method.setToolTip("Measurement method used by PSD runtime policy resolution.")
        self.cb_psd_result_unit.setToolTip("Displayed/runtime PSD result unit for this band.")
        self.cb_psd_comparator.setToolTip("Verdict comparison direction for PSD results.")
        self.ed_psd_limit_value.setToolTip("Band-level PSD limit value.")
        self.cb_psd_limit_unit.setToolTip("Unit for the PSD limit value.")
        self.tabs.addTab(self._wrap_tab_page(tab), self.SECTION_TABS[2])

    def _build_voltage_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.addWidget(self._make_help_banner(
            "Voltage is an optional axis.\n"
            "When enabled, the engine expands cases by voltage level only for tests listed in apply_to."
        ))
        self.chk_voltage_enabled = QCheckBox("Voltage policy enabled")
        layout.addWidget(self.chk_voltage_enabled)
        self.voltage_apply_to_checks = self._build_test_type_checkboxes()
        layout.addWidget(self._wrap_checkbox_grid("Apply To", self.voltage_apply_to_checks))
        self.voltage_levels_table = QTableWidget(0, 3)
        self.voltage_levels_table.setHorizontalHeaderLabels(["Name", "Label", "Percent Offset"])
        self.voltage_levels_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("Percent Levels"))
        layout.addWidget(self.voltage_levels_table, 1)
        row = QHBoxLayout()
        self.btn_voltage_level_add = QPushButton("Add Level")
        self.btn_voltage_level_remove = QPushButton("Remove Level")
        row.addWidget(self.btn_voltage_level_add)
        row.addWidget(self.btn_voltage_level_remove)
        row.addStretch(1)
        layout.addLayout(row)
        self.chk_voltage_enabled.setToolTip("Enable voltage-based case expansion.")
        self.voltage_levels_table.setToolTip("Each row creates one voltage axis value such as LOW, NOMINAL, or HIGH.")
        self.tabs.addTab(self._wrap_tab_page(tab), self.SECTION_TABS[3])

    def _build_data_rate_tab(self) -> None:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setSpacing(10)
        outer.addWidget(self._make_help_banner(
            "Data rate is an optional axis.\n"
            "Rates are resolved by standard, then expanded only for tests included in apply_to."
        ))
        layout = QHBoxLayout()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Apply To"))
        self.data_rate_apply_to_checks = self._build_test_type_checkboxes()
        left_layout.addWidget(self._wrap_checkbox_grid("", self.data_rate_apply_to_checks))
        left_layout.addWidget(QLabel("Standards"))
        self.rate_standard_list = QListWidget()
        left_layout.addWidget(self.rate_standard_list, 1)
        row = QHBoxLayout()
        self.btn_rate_standard_add = QPushButton("Add Standard")
        self.btn_rate_standard_remove = QPushButton("Remove Standard")
        row.addWidget(self.btn_rate_standard_add)
        row.addWidget(self.btn_rate_standard_remove)
        left_layout.addLayout(row)
        layout.addWidget(left, 0)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.ed_rate_values = QPlainTextEdit()
        self.ed_rate_values.setPlaceholderText("One rate per line or comma-separated values")
        right_layout.addWidget(QLabel("Rates for selected standard"))
        right_layout.addWidget(self.ed_rate_values, 1)
        layout.addWidget(right, 1)
        outer.addLayout(layout, 1)
        self.ed_rate_values.setToolTip("One rate per line or comma-separated values for the selected standard.")
        self.tabs.addTab(self._wrap_tab_page(tab), self.SECTION_TABS[4])

    def _build_test_contracts_tab(self) -> None:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setSpacing(10)
        outer.addWidget(self._make_help_banner(
            "Rulesets select test items from the global pool.\n"
            "Contracts shown here are pool-backed projections, and band enable state controls tests_supported."
        ))
        layout = QHBoxLayout()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Selected Test Items"))
        self.contract_list = QListWidget()
        left_layout.addWidget(self.contract_list, 1)
        row = QHBoxLayout()
        self.btn_contract_add = QPushButton("Add Test Item")
        self.btn_contract_remove = QPushButton("Remove Test Item")
        row.addWidget(self.btn_contract_add)
        row.addWidget(self.btn_contract_remove)
        left_layout.addLayout(row)
        layout.addWidget(left, 0)
        right = QWidget()
        form = QFormLayout(right)
        self.lb_contract_name = QLabel("")
        self.lb_contract_name.setWordWrap(True)
        self.lb_contract_test_id = QLabel("")
        self.lb_contract_measurement_class = QLabel("")
        self.lb_contract_default_profile_ref = QLabel("")
        self.lb_contract_required_instruments = QLabel("")
        self.lb_contract_result_fields = QLabel("")
        self.lb_contract_verdict_type = QLabel("")
        self.lb_contract_procedure_key = QLabel("")
        self.contract_band_checks_container = QWidget()
        self.contract_band_checks_layout = QVBoxLayout(self.contract_band_checks_container)
        self.contract_band_checks_layout.setContentsMargins(0, 0, 0, 0)
        self.contract_band_checks: Dict[str, QCheckBox] = {}
        form.addRow("Display Name", self.lb_contract_name)
        form.addRow("Canonical Test ID", self.lb_contract_test_id)
        form.addRow("Measurement Class", self.lb_contract_measurement_class)
        form.addRow("Default Profile Ref", self.lb_contract_default_profile_ref)
        form.addRow("Required Instruments", self.lb_contract_required_instruments)
        form.addRow("Result Fields", self.lb_contract_result_fields)
        form.addRow("Verdict Type", self.lb_contract_verdict_type)
        form.addRow("Procedure Key", self.lb_contract_procedure_key)
        form.addRow("Enabled Bands", self.contract_band_checks_container)
        layout.addWidget(right, 1)
        outer.addLayout(layout, 1)
        self.lb_contract_default_profile_ref.setToolTip("Pool default profile reference projected into compat test_contracts.")
        self.lb_contract_required_instruments.setToolTip("Required instruments come from the global pool definition.")
        self.lb_contract_verdict_type.setToolTip("Verdict contract projected from the global test item definition.")
        self.lb_contract_procedure_key.setToolTip("Only items with a procedure key are selectable.")
        self.tabs.addTab(self._wrap_tab_page(tab), self.SECTION_TABS[5])

    def _build_validation_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.addWidget(self._make_help_banner(
            "Validate checks policy consistency before saving.\n"
            "Preview Cases explains how base axes and optional axes combine into executable cases."
        ))
        self.validation_list = QListWidget()
        self.validation_list.setToolTip("Click a message to jump to the related tab and field.")
        layout.addWidget(QLabel("Validation Messages"))
        layout.addWidget(self.validation_list, 1)
        self.lb_preview_explanation = QLabel(
            "Each preview row is generated from base axes plus optional axis combinations. "
            "Use the summary and breakdown below to understand why case counts grow."
        )
        self.lb_preview_explanation.setWordWrap(True)
        layout.addWidget(self.lb_preview_explanation)
        layout.addWidget(QLabel("Preview Summary"))
        self.preview_summary = QPlainTextEdit()
        self.preview_summary.setReadOnly(True)
        self.preview_summary.setFixedHeight(150)
        layout.addWidget(self.preview_summary)
        layout.addWidget(QLabel("Axis Breakdown"))
        self.axis_breakdown_table = QTableWidget(0, 7)
        self.axis_breakdown_table.setHorizontalHeaderLabels(
            ["Axis", "Type", "Source", "Apply To", "Mode", "Resolved Values", "Impact"]
        )
        self.axis_breakdown_table.horizontalHeader().setStretchLastSection(True)
        self.axis_breakdown_table.setMinimumHeight(180)
        layout.addWidget(self.axis_breakdown_table)
        self.lb_preview_count = QLabel("Preview Cases: 0")
        layout.addWidget(self.lb_preview_count)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Test Filter"))
        self.cb_preview_test_filter = QComboBox()
        self.cb_preview_test_filter.addItem("All Tests", "")
        self.cb_preview_test_filter.setMinimumWidth(150)
        filter_row.addWidget(self.cb_preview_test_filter)
        filter_row.addWidget(QLabel("Axis Filter"))
        self.cb_preview_axis_filter = QComboBox()
        self.cb_preview_axis_filter.addItem("All Rows", "")
        self.cb_preview_axis_filter.addItem("Data Rate Rows", "data_rate")
        self.cb_preview_axis_filter.addItem("Voltage Rows", "voltage")
        self.cb_preview_axis_filter.setMinimumWidth(150)
        filter_row.addWidget(self.cb_preview_axis_filter)
        self.chk_preview_expanded_only = QCheckBox("Only Expanded Rows")
        filter_row.addWidget(self.chk_preview_expanded_only)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)
        self.preview_case_table = QTableWidget(0, 8)
        self.preview_case_table.setHorizontalHeaderLabels(
            ["Test", "Standard", "Band", "Channel", "Bandwidth", "Data Rate", "Voltage", "Target Voltage"]
        )
        self.preview_case_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.preview_case_table, 1)
        self.json_preview = QPlainTextEdit()
        self.json_preview.setReadOnly(True)
        layout.addWidget(QLabel("Ruleset JSON Preview"))
        layout.addWidget(self.json_preview, 1)
        self.tabs.addTab(self._wrap_tab_page(tab), self.SECTION_TABS[6])

    def _make_help_banner(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setProperty("role", "help-banner")
        self._help_banners.append(label)
        return label

    def _make_card(self, title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setProperty("role", "card")
        self._card_frames.append(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setProperty("role", "card-title")
        self._card_title_labels.append(title_label)
        layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setProperty("role", "card-subtitle")
            self._card_subtitle_labels.append(subtitle_label)
            layout.addWidget(subtitle_label)
        return frame, layout

    def _wrap_tab_page(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(page)
        return scroll

    def _apply_dialog_geometry(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1180, 760)
            self.setMinimumSize(760, 540)
            return
        available = screen.availableGeometry()
        target_width = max(760, min(int(available.width() * 0.84), 1180))
        target_height = max(560, min(int(available.height() * 0.84), 780))
        self.setMinimumSize(min(target_width, 760), min(target_height, 560))
        self.resize(target_width, target_height)

    def _configure_combo_boxes(self, parent: QWidget) -> None:
        combo_boxes = parent.findChildren(QComboBox)
        for combo in combo_boxes:
            combo.setMinimumContentsLength(max(combo.minimumContentsLength(), 10))
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumHeight(30)
            combo.setMaxVisibleItems(18)
            combo.setToolTip(combo.currentText().strip())
            combo.currentTextChanged.connect(combo.setToolTip)
            view = combo.view()
            if view is not None:
                view.setTextElideMode(Qt.ElideNone)

    def _is_dark_palette(self) -> bool:
        color = self.palette().window().color()
        luminance = (0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF())
        return luminance < 0.5

    def _blend_color(self, base: QColor, overlay: QColor, ratio: float) -> QColor:
        ratio = max(0.0, min(float(ratio), 1.0))
        inv = 1.0 - ratio
        return QColor(
            int((base.red() * inv) + (overlay.red() * ratio)),
            int((base.green() * inv) + (overlay.green() * ratio)),
            int((base.blue() * inv) + (overlay.blue() * ratio)),
        )

    def _semantic_colors(self) -> Dict[str, str]:
        palette = self.palette()
        dark = self._is_dark_palette()
        window = palette.window().color()
        base = palette.base().color()
        text = palette.text().color()
        mid = palette.mid().color()
        highlight = palette.highlight().color()
        accent = self._blend_color(highlight, text, 0.18 if dark else 0.08)
        return {
            "window_bg": self._blend_color(window, base, 0.12 if dark else 0.18).name(),
            "card_bg": self._blend_color(base, window, 0.30 if dark else 0.10).name(),
            "banner_bg": self._blend_color(window, accent, 0.14 if dark else 0.08).name(),
            "border": self._blend_color(mid, text, 0.10 if dark else 0.06).name(),
            "text": text.name(),
            "muted_text": self._blend_color(text, window, 0.35 if dark else 0.42).name(),
            "error": self._blend_color(QColor("#ef4444"), text, 0.18 if dark else 0.06).name(),
            "warning": self._blend_color(QColor("#d97706"), text, 0.14 if dark else 0.04).name(),
            "ok_border": self._blend_color(mid, window, 0.20 if dark else 0.05).name(),
        }

    def _apply_visual_polish(self) -> None:
        if self._applying_visual_polish:
            return
        self._applying_visual_polish = True
        try:
            colors = self._semantic_colors()
            self.setStyleSheet(
                "QDialog {"
                f"background: {colors['window_bg']};"
                f"color: {colors['text']};"
                "}"
                "QTabWidget::pane {"
                f"border: 1px solid {colors['border']};"
                "border-radius: 10px;"
                "top: -1px;"
                "}"
                "QTabBar::tab {"
                "padding: 8px 12px;"
                "margin-right: 4px;"
                "border-top-left-radius: 8px;"
                "border-top-right-radius: 8px;"
                "}"
                "QListWidget, QTableWidget, QPlainTextEdit, QLineEdit, QComboBox {"
                "border-radius: 8px;"
                "padding: 3px 6px;"
                "}"
                "QSplitter::handle {"
                f"background: {colors['border']};"
                "}"
                "QPushButton {"
                "padding: 6px 12px;"
                "border-radius: 8px;"
                "}"
                "QScrollArea {"
                "border: none;"
                "background: transparent;"
                "}"
            )
            for banner in self._help_banners:
                banner.setStyleSheet(
                    "QLabel {"
                    f"background: {colors['banner_bg']};"
                    f"border: 1px solid {colors['border']};"
                    "border-radius: 10px;"
                    "padding: 10px 12px;"
                    f"color: {colors['text']};"
                    "}"
                )
            for frame in self._card_frames:
                frame.setStyleSheet(
                    "QFrame {"
                    f"background: {colors['card_bg']};"
                    f"border: 1px solid {colors['border']};"
                    "border-radius: 14px;"
                    "}"
                )
            for label in self._card_title_labels:
                label.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {colors['text']};")
            for label in self._card_subtitle_labels:
                label.setStyleSheet(f"font-size: 12px; color: {colors['muted_text']};")
            if hasattr(self, "lb_basic_base_cases"):
                for widget in (
                    self.lb_basic_base_cases,
                    self.lb_basic_data_rate_multiplier,
                    self.lb_basic_voltage_multiplier,
                    self.lb_basic_total_cases,
                ):
                    widget.setStyleSheet(f"font-size: 14px; color: {colors['text']};")
        finally:
            self._applying_visual_polish = False

    def load_ruleset_data(self, ruleset_data: Dict[str, Any], *, source_path: str = "") -> None:
        self._loading = True
        try:
            data = dict(ruleset_data or {})
            data.setdefault("bands", {})
            data.setdefault("test_contracts", {})
            data.setdefault("instrument_profile_refs", {})
            data["case_dimensions"] = normalize_case_dimensions(data.get("case_dimensions") or {})
            data["voltage_policy"] = normalize_voltage_policy(data.get("voltage_policy") or {})
            data["data_rate_policy"] = normalize_data_rate_policy(data.get("data_rate_policy") or {})
            data["test_contracts"] = project_ruleset_test_contracts(
                data.get("test_contracts") or {},
                tests_supported=collect_ruleset_test_types(data),
            )
            self._ruleset_data = data
            self._current_path = source_path

            self.ed_ruleset_id.setText(str(data.get("id", "")))
            self.ed_ruleset_version.setText(str(data.get("version", "")))
            self.ed_regulation.setText(str(data.get("regulation", "")))
            self.ed_tech.setText(str(data.get("tech", "")))
            self.ed_schema_version.setText(str(data.get("schema_version", 2)))
            self.lb_source_path.setText(source_path or "(unsaved)")

            self._reload_dimension_list()
            self._reload_band_list()
            self._load_voltage_policy()
            self._reload_standard_rate_list()
            self._reload_contract_list()
            self._sync_basic_mode_from_ruleset(data)
            self._reload_basic_mode_controls(data)
            self.cb_ui_mode.setCurrentIndex(0 if self._ui_mode == "basic" else 1)
            self._apply_ui_mode_visibility()
            self._refresh_json_preview(self._ruleset_data)
            self.validation_list.clear()
            self.preview_case_table.setRowCount(0)
            self.lb_preview_count.setText("Preview Cases: 0")
            self.preview_summary.setPlainText("")
            self.axis_breakdown_table.setRowCount(0)
            self.cb_preview_test_filter.blockSignals(True)
            self.cb_preview_test_filter.clear()
            self.cb_preview_test_filter.addItem("All Tests", "")
            self.cb_preview_test_filter.blockSignals(False)
            self._preview_rows = []
            self._preview_analysis = {}
        finally:
            self._loading = False
        self._run_live_feedback()

    def collect_ruleset_data(self) -> Dict[str, Any]:
        if self._current_dimension_name():
            self._commit_dimension_into_internal(self._current_dimension_name())
        data = deepcopy(self._ruleset_data)
        data["id"] = self.ed_ruleset_id.text().strip()
        data["version"] = self.ed_ruleset_version.text().strip()
        data["regulation"] = self.ed_regulation.text().strip()
        data["tech"] = self.ed_tech.text().strip()
        try:
            data["schema_version"] = int(self.ed_schema_version.text().strip() or "2")
        except Exception:
            data["schema_version"] = 2
        data["case_dimensions"] = self._collect_case_dimensions(data)
        self._commit_current_band_psd_policy(data)
        data["voltage_policy"] = self._collect_voltage_policy()
        data["data_rate_policy"] = self._collect_data_rate_policy(data)
        data["test_contracts"] = self._collect_test_contracts(data)
        data["test_contracts"] = project_ruleset_test_contracts(
            data.get("test_contracts") or {},
            tests_supported=collect_ruleset_test_types(data),
        )
        return data

    def on_load_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Ruleset", self._current_path or "rulesets", "JSON Files (*.json)")
        if not file_path:
            return
        try:
            raw = json.loads(Path(file_path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "Load Ruleset", str(exc))
            return
        self.load_ruleset_data(raw, source_path=file_path)

    def on_new_clicked(self, initial: bool = False) -> None:
        dialog = CreateRulesetDialog(self)
        if dialog.exec() != QDialog.Accepted:
            if initial:
                self.load_ruleset_data(load_template("CUSTOM_EMPTY"), source_path="")
            return
        template_id = dialog.selected_template_id()
        payload = load_template(template_id)
        self._current_path = ""
        self.load_ruleset_data(payload, source_path="")

    def on_save_clicked(self) -> None:
        if not self._current_path:
            self.on_save_as_clicked()
            return
        self._save_to_path(self._current_path)

    def on_save_as_clicked(self) -> None:
        suggested = self._current_path or str(Path("rulesets") / f"{self.ed_ruleset_id.text().strip().lower() or 'ruleset'}.json")
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Ruleset As", suggested, "JSON Files (*.json)")
        if not file_path:
            return
        self._save_to_path(file_path, save_mode="save_as")

    def on_clone_clicked(self) -> None:
        data = self.collect_ruleset_data()
        base_id = str(data.get("id", "")).strip() or "RULESET"
        data["id"] = f"{base_id}_COPY"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Clone Ruleset",
            str(Path("rulesets") / f"{data['id'].lower()}.json"),
            "JSON Files (*.json)",
        )
        if not file_path:
            return
        adjusted_id = self._confirm_ruleset_id_for_new_path(
            current_id=str(data.get("id", "")).strip(),
            target_path=file_path,
            mode="clone",
        )
        if adjusted_id is None:
            return
        data["id"] = adjusted_id
        self._save_payload_to_path(data, file_path)
        self.load_ruleset_data(data, source_path=file_path)

    def on_mode_changed(self) -> None:
        if self._loading:
            return
        new_mode = str(self.cb_ui_mode.currentData() or "basic")
        if self._ui_mode == "advanced" and new_mode == "basic":
            result = QMessageBox.question(
                self,
                "Switch To Basic Mode",
                "Advanced Mode contains detailed axis settings. Switching to Basic Mode may simplify or overwrite some axis details. Continue?",
            )
            if result != QMessageBox.Yes:
                self._loading = True
                try:
                    self.cb_ui_mode.setCurrentIndex(1)
                finally:
                    self._loading = False
                return
        self._ui_mode = new_mode
        self._apply_ui_mode_visibility()
        self._run_live_feedback()

    def on_validate_clicked(self) -> None:
        self._run_live_feedback()
        self.tabs.setCurrentIndex(self.SECTION_TABS.index("Validation"))

    def on_preview_cases_clicked(self) -> None:
        self._run_live_feedback()
        self.tabs.setCurrentIndex(self.SECTION_TABS.index("Validation"))

    def on_add_dimension(self) -> None:
        data = self.collect_ruleset_data()
        dimensions = dict((data.get("case_dimensions") or {}).get("dimensions") or {})
        name = self._next_available_name(dimensions.keys(), "axis")
        dimensions[name] = {
            "name": name,
            "type": "enum",
            "source": "",
            "maps_to": "",
            "values": [],
            "optional": False,
            "apply_to": [],
            "apply_to_defined": False,
            "non_applicable_mode": "OMIT",
            "policy_ref": "",
        }
        data["case_dimensions"]["dimensions"] = dimensions
        self.load_ruleset_data(data, source_path=self._current_path)
        self._select_list_item(self.dimension_list, name)

    def on_remove_dimension(self) -> None:
        current_name = self._current_dimension_name()
        if not current_name:
            return
        data = self.collect_ruleset_data()
        dimensions = dict((data.get("case_dimensions") or {}).get("dimensions") or {})
        dimensions.pop(current_name, None)
        data["case_dimensions"]["dimensions"] = dimensions
        self.load_ruleset_data(data, source_path=self._current_path)

    def on_add_standard_rates(self) -> None:
        data = self.collect_ruleset_data()
        by_standard = dict((data.get("data_rate_policy") or {}).get("by_standard") or {})
        name = self._next_available_name(by_standard.keys(), "STANDARD")
        by_standard[name] = []
        data["data_rate_policy"]["by_standard"] = by_standard
        self.load_ruleset_data(data, source_path=self._current_path)
        self._select_list_item(self.rate_standard_list, name)

    def on_remove_standard_rates(self) -> None:
        current_name = self._current_rate_standard()
        if not current_name:
            return
        data = self.collect_ruleset_data()
        by_standard = dict((data.get("data_rate_policy") or {}).get("by_standard") or {})
        by_standard.pop(current_name, None)
        data["data_rate_policy"]["by_standard"] = by_standard
        self.load_ruleset_data(data, source_path=self._current_path)

    def on_add_contract(self) -> None:
        data = self.collect_ruleset_data()
        selected_test_ids, selected_bands = self._select_pool_test_items(data)
        if not selected_test_ids:
            return
        data = self._enable_test_items_for_ruleset(data, selected_test_ids, selected_bands)
        self.load_ruleset_data(data, source_path=self._current_path)
        self._select_list_item(self.contract_list, selected_test_ids[0])

    def on_remove_contract(self) -> None:
        current_test_id = self._current_contract_name()
        if not current_test_id:
            return
        data = self.collect_ruleset_data()
        data = self._disable_test_item_for_ruleset(data, current_test_id)
        self.load_ruleset_data(data, source_path=self._current_path)

    def _save_to_path(self, file_path: str, *, save_mode: str = "save") -> None:
        data = self.collect_ruleset_data()
        if save_mode == "save_as":
            adjusted_id = self._confirm_ruleset_id_for_new_path(
                current_id=str(data.get("id", "")).strip(),
                target_path=file_path,
                mode="save_as",
            )
            if adjusted_id is None:
                return
            data["id"] = adjusted_id
            self.ed_ruleset_id.setText(adjusted_id)
        validation = validate_ruleset_payload(data)
        if validation["errors"]:
            self._show_validation_results(validation)
            QMessageBox.warning(self, "Save Ruleset", "Fix validation errors before saving.")
            self.tabs.setCurrentIndex(self.SECTION_TABS.index("Validation"))
            return
        duplicate_path = self._find_duplicate_ruleset_id_path(
            str(data.get("id", "")).strip(),
            exclude_path=file_path,
        )
        if duplicate_path:
            QMessageBox.warning(
                self,
                "Save Ruleset",
                "Another ruleset already uses this RuleSet ID.\n\n"
                f"RuleSet ID: {data.get('id', '')}\n"
                f"Existing File: {duplicate_path}\n\n"
                "Use a different RuleSet ID before saving.",
            )
            return
        self._warn_if_filename_mismatch(str(data.get("id", "")).strip(), file_path)
        self._save_payload_to_path(data, file_path)
        self.load_ruleset_data(data, source_path=file_path)

    def _save_payload_to_path(self, data: Dict[str, Any], file_path: str) -> None:
        try:
            Path(file_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Save Ruleset", str(exc))
            return
        QMessageBox.information(self, "Save Ruleset", f"Saved ruleset JSON:\n{file_path}")

    def _confirm_ruleset_id_for_new_path(
        self,
        *,
        current_id: str,
        target_path: str,
        mode: str,
    ) -> str | None:
        normalized_id = str(current_id or "").strip()
        suggested_id = self._suggest_ruleset_id_for_path(target_path)
        if not normalized_id:
            normalized_id = suggested_id
        current_path = str(self._current_path or "").strip()
        creating_new_file = not current_path or str(Path(current_path)) != str(Path(target_path))
        if not creating_new_file:
            return normalized_id
        if not normalized_id:
            return suggested_id
        if normalized_id == suggested_id:
            return normalized_id

        prompt_title = "Clone Ruleset" if mode == "clone" else "Save Ruleset As"
        action_label = "clone" if mode == "clone" else "save as"
        result = QMessageBox.question(
            self,
            prompt_title,
            f"You are about to {action_label} to a new file.\n\n"
            f"Current RuleSet ID: {normalized_id}\n"
            f"Suggested RuleSet ID: {suggested_id}\n\n"
            "Use the suggested RuleSet ID for the new file?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if result == QMessageBox.Cancel:
            return None
        if result == QMessageBox.Yes:
            return suggested_id
        return normalized_id

    def _suggest_ruleset_id_for_path(self, file_path: str) -> str:
        stem = Path(file_path).stem.strip()
        if not stem:
            return "RULESET"
        out: list[str] = []
        for ch in stem:
            if ch.isalnum():
                out.append(ch.upper())
            else:
                out.append("_")
        suggested = "".join(out).strip("_")
        while "__" in suggested:
            suggested = suggested.replace("__", "_")
        return suggested or "RULESET"

    def _find_duplicate_ruleset_id_path(self, ruleset_id: str, *, exclude_path: str = "") -> str:
        target_id = str(ruleset_id or "").strip().upper()
        if not target_id:
            return ""
        excluded = str(Path(exclude_path).resolve()) if exclude_path else ""
        ruleset_dir = Path("rulesets")
        if not ruleset_dir.exists():
            return ""
        for path in sorted(ruleset_dir.glob("*.json")):
            try:
                resolved = str(path.resolve())
            except Exception:
                resolved = str(path)
            if excluded and resolved == excluded:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            existing_id = str(payload.get("id", "")).strip().upper()
            if existing_id and existing_id == target_id:
                return resolved
        return ""

    def _warn_if_filename_mismatch(self, ruleset_id: str, file_path: str) -> None:
        suggested_id = self._suggest_ruleset_id_for_path(file_path)
        normalized_id = str(ruleset_id or "").strip().upper()
        if not normalized_id or normalized_id == suggested_id:
            return
        QMessageBox.information(
            self,
            "RuleSet ID Check",
            "The file name and RuleSet ID do not match exactly.\n\n"
            f"File Suggests: {suggested_id}\n"
            f"Current RuleSet ID: {ruleset_id}\n\n"
            "This is allowed, but presets reference RuleSet ID, so keeping them aligned is recommended.",
        )

    def _collect_case_dimensions(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if self._ui_mode == "basic":
            return self._collect_case_dimensions_basic(data)
        dimensions = deepcopy(dict((data.get("case_dimensions") or {}).get("dimensions") or {}))
        current_name = self._current_dimension_name()
        if current_name:
            old_key = current_name
            new_key = self.ed_dimension_name.text().strip() or old_key
            axis_payload = {
                "name": new_key,
                "type": self.cb_dimension_type.currentText().strip() or "enum",
                "source": self.ed_dimension_source.text().strip(),
                "maps_to": self.ed_dimension_maps_to.text().strip(),
                "values": self._collect_table_column(self.dimension_values_table, 0),
                "optional": self.chk_dimension_optional.isChecked(),
                "apply_to": self._collect_checked_test_types(self.dimension_apply_to_checks),
                "non_applicable_mode": self.cb_dimension_non_applicable_mode.currentText().strip() or "OMIT",
                "policy_ref": "",
            }
            dimensions.pop(old_key, None)
            dimensions[new_key] = axis_payload
        ordered_names = [self.dimension_list.item(i).text() for i in range(self.dimension_list.count())]
        if current_name:
            new_key = self.ed_dimension_name.text().strip() or current_name
            ordered_names = [new_key if name == current_name else name for name in ordered_names]
        ordered_names = [name for name in ordered_names if name in dimensions]
        optional_axes = []
        for axis_name in ordered_names:
            axis_payload = dict(dimensions.get(axis_name) or {})
            if bool(axis_payload.get("optional")):
                optional_axes.append({
                    "name": axis_name,
                    "policy_ref": str(axis_payload.get("policy_ref", "") or ""),
                })
        return normalize_case_dimensions({
            "defined": True,
            "base": ordered_names,
            "optional_axes": optional_axes,
            "dimensions": dimensions,
        })

    def _collect_case_dimensions_basic(self, data: Dict[str, Any]) -> Dict[str, Any]:
        dimensions = dict((normalize_case_dimensions(data.get("case_dimensions") or {})).get("dimensions") or {})
        basic_apply_to = self._collect_checked_test_types(self.basic_apply_to_checks)
        basic_dimensions = {
            "frequency_band": {
                "name": "frequency_band",
                "type": "enum",
                "source": "bands",
                "maps_to": "band",
                "values": [str(name).strip() for name in dict(data.get("bands") or {}).keys() if str(name).strip()],
                "optional": False,
                "apply_to": [],
                "non_applicable_mode": "OMIT",
                "policy_ref": "",
            },
            "standard": {
                "name": "standard",
                "type": "enum",
                "source": "preset.standard_or_wlan_expansion",
                "maps_to": "standard",
                "values": [],
                "optional": False,
                "apply_to": [],
                "non_applicable_mode": "OMIT",
                "policy_ref": "",
            },
            "bandwidth": {
                "name": "bandwidth",
                "type": "numeric",
                "source": "preset.bandwidth_mhz",
                "maps_to": "bw_mhz",
                "values": [],
                "optional": False,
                "apply_to": [],
                "non_applicable_mode": "OMIT",
                "policy_ref": "",
            },
            "channel": {
                "name": "channel",
                "type": "numeric",
                "source": "channel_groups",
                "maps_to": "channel",
                "values": [],
                "optional": False,
                "apply_to": [],
                "non_applicable_mode": "OMIT",
                "policy_ref": "",
            },
        }
        if self.chk_basic_data_rate.isChecked():
            basic_dimensions["data_rate"] = {
                "name": "data_rate",
                "type": "enum",
                "source": "data_rate_policy",
                "maps_to": "tags.data_rate",
                "values": [],
                "optional": True,
                "apply_to": basic_apply_to or ["PSD", "RX"],
                "non_applicable_mode": "EMPTY_VALUE",
                "policy_ref": "data_rate_policy",
            }
        if self.chk_basic_voltage.isChecked():
            basic_dimensions["voltage"] = {
                "name": "voltage",
                "type": "computed",
                "source": "voltage_policy",
                "maps_to": "tags.voltage_condition",
                "values": [],
                "optional": True,
                "apply_to": basic_apply_to or ["PSD", "OBW", "SP"],
                "non_applicable_mode": "EMPTY_VALUE",
                "policy_ref": "voltage_policy",
            }
        if self.chk_basic_temperature.isChecked():
            basic_dimensions["temperature"] = {
                "name": "temperature",
                "type": "enum",
                "source": "",
                "maps_to": "tags.temperature",
                "values": ["ROOM"],
                "optional": True,
                "apply_to": [],
                "non_applicable_mode": "EMPTY_VALUE",
                "policy_ref": "",
            }
        if self.chk_basic_power_mode.isChecked():
            basic_dimensions["power_mode"] = {
                "name": "power_mode",
                "type": "enum",
                "source": "",
                "maps_to": "tags.power_mode",
                "values": ["DEFAULT"],
                "optional": True,
                "apply_to": [],
                "non_applicable_mode": "EMPTY_VALUE",
                "policy_ref": "",
            }
        for axis_name, axis_payload in dimensions.items():
            if axis_name not in basic_dimensions and axis_name in {"temperature", "power_mode"}:
                basic_dimensions[axis_name] = axis_payload
        optional_axes = []
        for axis_name, axis_payload in basic_dimensions.items():
            if bool(axis_payload.get("optional")):
                optional_axes.append({
                    "name": axis_name,
                    "policy_ref": str(axis_payload.get("policy_ref", "") or ""),
                })
        return normalize_case_dimensions({
            "defined": True,
            "base": ["test_type", "standard", "frequency_band", "bandwidth", "channel"],
            "optional_axes": optional_axes,
            "dimensions": basic_dimensions,
        })

    def _commit_current_band_psd_policy(self, data: Dict[str, Any]) -> None:
        current_band = self._current_band_name()
        if not current_band:
            return
        bands = dict(data.get("bands") or {})
        band_payload = dict(bands.get(current_band) or {})
        band_payload["psd_policy"] = {
            "method": self.cb_psd_method.currentText().strip(),
            "result_unit": self.cb_psd_result_unit.currentText().strip(),
            "comparator": self.cb_psd_comparator.currentText().strip(),
            "limit": {
                "value": self._parse_float(self.ed_psd_limit_value.text()),
                "unit": self.cb_psd_limit_unit.currentText().strip(),
            },
        }
        bands[current_band] = band_payload
        data["bands"] = bands

    def _collect_voltage_policy(self) -> Dict[str, Any]:
        existing_policy = normalize_voltage_policy(self._ruleset_data.get("voltage_policy") or {})
        collected_apply_to = self._collect_checked_test_types(self.voltage_apply_to_checks)
        collected_levels = self._collect_table_rows(self.voltage_levels_table, ("name", "label", "percent_offset"))
        default_levels = [
            {"name": "LOW", "label": "Low (-5%)", "percent_offset": -5},
            {"name": "NOMINAL", "label": "Nominal", "percent_offset": 0},
            {"name": "HIGH", "label": "High (+5%)", "percent_offset": 5},
        ]
        if self._ui_mode == "basic":
            selected_basic_levels: List[Dict[str, Any]] = []
            if self.chk_basic_voltage_low.isChecked():
                selected_basic_levels.append({"name": "LOW", "label": "Low (-10%)", "percent_offset": -10})
            if self.chk_basic_voltage_nominal.isChecked():
                selected_basic_levels.append({"name": "NOMINAL", "label": "Nominal", "percent_offset": 0})
            if self.chk_basic_voltage_high.isChecked():
                selected_basic_levels.append({"name": "HIGH", "label": "High (+10%)", "percent_offset": 10})
            if self.chk_basic_voltage.isChecked() and not selected_basic_levels:
                selected_basic_levels = [{"name": "NOMINAL", "label": "Nominal", "percent_offset": 0}]
            basic_apply_to = self._collect_checked_test_types(self.basic_apply_to_checks)
            if not self.chk_basic_voltage.isChecked():
                return normalize_voltage_policy({
                    "enabled": False,
                    "mode": "PERCENT_OF_NOMINAL",
                    "nominal_source": "preset.nominal_voltage_v",
                    "apply_to": [],
                    "settle_time_ms": existing_policy.get("settle_time_ms", 0),
                    "fallback_policy": existing_policy.get("fallback_policy", "WARN_AND_CONTINUE"),
                    "levels": [],
                })
            return normalize_voltage_policy({
                "enabled": True,
                "mode": "PERCENT_OF_NOMINAL",
                "nominal_source": "preset.nominal_voltage_v",
                "apply_to": basic_apply_to or collected_apply_to or list(existing_policy.get("apply_to") or []) or ["PSD", "OBW", "SP"],
                "settle_time_ms": existing_policy.get("settle_time_ms", 500),
                "fallback_policy": existing_policy.get("fallback_policy", "WARN_AND_CONTINUE"),
                "levels": selected_basic_levels or collected_levels or list(existing_policy.get("levels") or []) or list(default_levels),
            })
        return normalize_voltage_policy({
            "enabled": self.chk_voltage_enabled.isChecked(),
            "mode": "PERCENT_OF_NOMINAL",
            "nominal_source": "preset.nominal_voltage_v",
            "apply_to": collected_apply_to,
            "settle_time_ms": existing_policy.get("settle_time_ms", 0),
            "fallback_policy": existing_policy.get("fallback_policy", "WARN_AND_CONTINUE"),
            "levels": collected_levels,
        })

    def _collect_data_rate_policy(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if self._ui_mode == "basic":
            if not self.chk_basic_data_rate.isChecked():
                return normalize_data_rate_policy({
                    "enabled": False,
                    "apply_to": [],
                    "non_applicable_mode": "OMIT",
                    "by_standard": {},
                })
            bands = dict(data.get("bands") or {})
            standards: Dict[str, List[str]] = {}
            for _, band_payload in bands.items():
                if not isinstance(band_payload, dict):
                    continue
                for standard in [str(item).strip() for item in (band_payload.get("standards") or []) if str(item).strip()]:
                    standards.setdefault(standard, self._default_rates_for_standard(standard))
            return normalize_data_rate_policy({
                "enabled": True,
                "apply_to": self._collect_checked_test_types(self.basic_apply_to_checks) or ["PSD", "RX"],
                "non_applicable_mode": "OMIT",
                "by_standard": standards,
            })
        current_standard = self._current_rate_standard()
        by_standard = deepcopy(dict((data.get("data_rate_policy") or {}).get("by_standard") or {}))
        if current_standard:
            by_standard[current_standard] = self._parse_csv_or_lines(self.ed_rate_values.toPlainText(), uppercase=True)
        return normalize_data_rate_policy({
            "enabled": True,
            "apply_to": self._collect_checked_test_types(self.data_rate_apply_to_checks),
            "non_applicable_mode": "OMIT",
            "by_standard": by_standard,
        })

    def _collect_test_contracts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return project_ruleset_test_contracts(
            data.get("test_contracts") or {},
            tests_supported=collect_ruleset_test_types(data),
        )

    def _commit_dimension_into_internal(self, current_name: str) -> None:
        if not current_name:
            return
        if self._ui_mode == "basic":
            return
        data = deepcopy(self._ruleset_data)
        dimensions = dict((data.get("case_dimensions") or {}).get("dimensions") or {})
        new_key = self.ed_dimension_name.text().strip() or current_name
        payload = {
            "name": new_key,
            "type": self.cb_dimension_type.currentText().strip() or "enum",
            "source": self.ed_dimension_source.text().strip(),
            "maps_to": self.ed_dimension_maps_to.text().strip(),
            "values": self._collect_table_column(self.dimension_values_table, 0),
            "optional": self.chk_dimension_optional.isChecked(),
            "apply_to": self._collect_checked_test_types(self.dimension_apply_to_checks),
            "non_applicable_mode": self.cb_dimension_non_applicable_mode.currentText().strip() or "OMIT",
            "policy_ref": "",
        }
        dimensions.pop(current_name, None)
        dimensions[new_key] = payload
        data["case_dimensions"] = normalize_case_dimensions({
            "defined": True,
            "base": [new_key if self.dimension_list.item(i).text() == current_name else self.dimension_list.item(i).text() for i in range(self.dimension_list.count())],
            "optional_axes": [],
            "dimensions": dimensions,
        })
        self._ruleset_data = data

    def _commit_band_psd_into_internal(self, band_name: str) -> None:
        if not band_name:
            return
        data = deepcopy(self._ruleset_data)
        bands = dict(data.get("bands") or {})
        band_payload = dict(bands.get(band_name) or {})
        band_payload["psd_policy"] = {
            "method": self.cb_psd_method.currentText().strip(),
            "result_unit": self.cb_psd_result_unit.currentText().strip(),
            "comparator": self.cb_psd_comparator.currentText().strip(),
            "limit": {
                "value": self._parse_float(self.ed_psd_limit_value.text()),
                "unit": self.cb_psd_limit_unit.currentText().strip(),
            },
        }
        bands[band_name] = band_payload
        data["bands"] = bands
        self._ruleset_data = data

    def _commit_standard_rates_into_internal(self, standard_name: str) -> None:
        if not standard_name:
            return
        data = deepcopy(self._ruleset_data)
        policy = dict(data.get("data_rate_policy") or {})
        by_standard = dict(policy.get("by_standard") or {})
        by_standard[standard_name] = self._parse_csv_or_lines(self.ed_rate_values.toPlainText(), uppercase=True)
        policy["by_standard"] = by_standard
        data["data_rate_policy"] = normalize_data_rate_policy(policy)
        self._ruleset_data = data

    def _commit_contract_into_internal(self, contract_name: str) -> None:
        return

    def _reload_dimension_list(self) -> None:
        dimensions = dict((self._ruleset_data.get("case_dimensions") or {}).get("dimensions") or {})
        self.dimension_list.clear()
        for name in dimensions.keys():
            self.dimension_list.addItem(name)
        if self.dimension_list.count() > 0:
            self.dimension_list.setCurrentRow(0)
        else:
            self._load_dimension_payload("", {})

    def _reload_band_list(self) -> None:
        self.band_list.clear()
        for name in dict(self._ruleset_data.get("bands") or {}).keys():
            self.band_list.addItem(name)
        if self.band_list.count() > 0:
            self.band_list.setCurrentRow(0)
        else:
            self._load_band_psd_payload("", {})

    def _load_voltage_policy(self) -> None:
        policy = normalize_voltage_policy(self._ruleset_data.get("voltage_policy") or {})
        self.chk_voltage_enabled.setChecked(bool(policy.get("enabled")))
        self._set_checked_test_types(self.voltage_apply_to_checks, list(policy.get("apply_to") or []))
        self._fill_table(self.voltage_levels_table, list(policy.get("levels") or []), ("name", "label", "percent_offset"))
        self._sync_basic_voltage_level_labels(list(policy.get("levels") or []))

    def _reload_standard_rate_list(self) -> None:
        self.rate_standard_list.clear()
        by_standard = dict((self._ruleset_data.get("data_rate_policy") or {}).get("by_standard") or {})
        self._set_checked_test_types(self.data_rate_apply_to_checks, list((self._ruleset_data.get("data_rate_policy") or {}).get("apply_to") or []))
        for standard in by_standard.keys():
            self.rate_standard_list.addItem(standard)
        if self.rate_standard_list.count() > 0:
            self.rate_standard_list.setCurrentRow(0)
        else:
            self.ed_rate_values.setPlainText("")

    def _sync_basic_voltage_level_labels(self, levels: List[Dict[str, Any]]) -> None:
        level_map = {
            str(item.get("name", "")).strip().upper(): dict(item)
            for item in (levels or [])
            if str(item.get("name", "")).strip()
        }
        self.chk_basic_voltage_nominal.setText(self._basic_voltage_checkbox_text("NOMINAL", level_map.get("NOMINAL")))
        self.chk_basic_voltage_high.setText(self._basic_voltage_checkbox_text("HIGH", level_map.get("HIGH")))
        self.chk_basic_voltage_low.setText(self._basic_voltage_checkbox_text("LOW", level_map.get("LOW")))

    def _basic_voltage_checkbox_text(self, level_name: str, payload: Dict[str, Any] | None) -> str:
        name = str(level_name or "").strip().upper()
        label = str((payload or {}).get("label", "") or "").strip()
        percent_offset = self._parse_float((payload or {}).get("percent_offset"))
        if label:
            return label
        suggested = self._suggest_voltage_label(name, percent_offset)
        if suggested:
            return suggested
        if name == "NOMINAL":
            return "Nominal"
        if name == "HIGH":
            return "High (+10%)"
        if name == "LOW":
            return "Low (-10%)"
        return name.title()

    def _reload_contract_list(self) -> None:
        self.contract_list.clear()
        for name in collect_ruleset_test_types(self._ruleset_data):
            self.contract_list.addItem(name)
        if self.contract_list.count() > 0:
            self.contract_list.setCurrentRow(0)
        else:
            self._load_contract_payload("", {})

    def _sync_basic_mode_from_ruleset(self, data: Dict[str, Any]) -> None:
        dimensions = dict((data.get("case_dimensions") or {}).get("dimensions") or {})
        voltage_policy = normalize_voltage_policy(data.get("voltage_policy") or {})
        data_rate_policy = normalize_data_rate_policy(data.get("data_rate_policy") or {})
        self.chk_basic_voltage.setChecked(bool(dimensions.get("voltage")) or bool(voltage_policy.get("enabled")))
        self.chk_basic_data_rate.setChecked(bool(dimensions.get("data_rate")) or bool(data_rate_policy.get("enabled")))
        self.chk_basic_temperature.setChecked(bool(dimensions.get("temperature")))
        self.chk_basic_power_mode.setChecked(bool(dimensions.get("power_mode")))
        selected_levels = {
            str(item.get("name", "")).strip().upper()
            for item in (voltage_policy.get("levels") or [])
            if str(item.get("name", "")).strip()
        }
        if not selected_levels:
            selected_levels = {"LOW", "NOMINAL", "HIGH"} if bool(voltage_policy.get("enabled")) else {"NOMINAL"}
        self.chk_basic_voltage_nominal.setChecked("NOMINAL" in selected_levels)
        self.chk_basic_voltage_high.setChecked("HIGH" in selected_levels)
        self.chk_basic_voltage_low.setChecked("LOW" in selected_levels)
        apply_to = list(voltage_policy.get("apply_to") or data_rate_policy.get("apply_to") or [])
        if not apply_to:
            apply_to = ["PSD", "OBW", "SP"]
        self._set_checked_test_types(self.basic_apply_to_checks, apply_to)

    def _reload_basic_mode_controls(self, data: Dict[str, Any]) -> None:
        current_standard = self.cb_basic_standard.currentText().strip()
        current_band = self.cb_basic_band.currentText().strip()
        current_group = self.cb_basic_channel_group.currentText().strip()

        bands = [str(name).strip() for name in dict(data.get("bands") or {}).keys() if str(name).strip()]
        selected_band = current_band if current_band in bands else ""

        standards: List[str] = []
        if selected_band:
            band_payload = dict((data.get("bands") or {}).get(selected_band) or {})
            standards = [
                str(item).strip()
                for item in (band_payload.get("standards") or [])
                if str(item).strip()
            ]
        if not standards:
            for band_payload in dict(data.get("bands") or {}).values():
                for item in (dict(band_payload or {}).get("standards") or []):
                    value = str(item).strip()
                    if value and value not in standards:
                        standards.append(value)

        channel_groups = []
        if selected_band:
            channel_groups = [
                str(name).strip()
                for name in dict((dict((data.get("bands") or {}).get(selected_band) or {})).get("channel_groups") or {}).keys()
                if str(name).strip()
            ]

        self.cb_basic_band.blockSignals(True)
        self.cb_basic_standard.blockSignals(True)
        self.cb_basic_channel_group.blockSignals(True)
        try:
            self.cb_basic_band.clear()
            self.cb_basic_band.addItem("All Bands", "")
            for value in bands:
                self.cb_basic_band.addItem(value, value)
            band_index = self.cb_basic_band.findData(selected_band)
            self.cb_basic_band.setCurrentIndex(band_index if band_index >= 0 else 0)

            self.cb_basic_standard.clear()
            self.cb_basic_standard.addItem("All Standards", "")
            for value in standards:
                self.cb_basic_standard.addItem(value, value)
            standard_index = self.cb_basic_standard.findData(current_standard if current_standard in standards else "")
            self.cb_basic_standard.setCurrentIndex(standard_index if standard_index >= 0 else 0)

            self.cb_basic_channel_group.clear()
            self.cb_basic_channel_group.addItem("All Groups", "")
            for value in channel_groups:
                self.cb_basic_channel_group.addItem(value, value)
            group_index = self.cb_basic_channel_group.findData(current_group if current_group in channel_groups else "")
            self.cb_basic_channel_group.setCurrentIndex(group_index if group_index >= 0 else 0)
        finally:
            self.cb_basic_band.blockSignals(False)
            self.cb_basic_standard.blockSignals(False)
            self.cb_basic_channel_group.blockSignals(False)

    def _apply_ui_mode_visibility(self) -> None:
        basic = self._ui_mode == "basic"
        self.basic_axis_widget.setVisible(basic)
        self.advanced_axis_widget.setVisible(not basic)

    def _default_rates_for_standard(self, standard: str) -> List[str]:
        defaults = {
            "802.11b": ["1M", "2M", "5.5M", "11M"],
            "802.11g": ["6M", "12M", "24M", "54M"],
            "802.11a": ["6M", "12M", "24M", "54M"],
            "802.11n": ["MCS0", "MCS7"],
            "802.11ac": ["MCS0", "MCS9"],
            "802.11ax": ["MCS0", "MCS11"],
            "802.11be": ["MCS0", "MCS13"],
        }
        return list(defaults.get(str(standard or "").strip(), ["DEFAULT_RATE"]))

    def _on_dimension_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if self._loading:
            return
        if previous is not None:
            self._commit_dimension_into_internal(previous.text().strip())
        if current is None:
            self._load_dimension_payload("", {})
            return
        payload = dict(((self._ruleset_data.get("case_dimensions") or {}).get("dimensions") or {}).get(current.text().strip()) or {})
        self._load_dimension_payload(current.text().strip(), payload)

    def _on_band_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if self._loading:
            return
        if previous is not None:
            self._commit_band_psd_into_internal(previous.text().strip())
        if current is None:
            self._load_band_psd_payload("", {})
            return
        payload = dict((self._ruleset_data.get("bands") or {}).get(current.text().strip()) or {})
        self._load_band_psd_payload(current.text().strip(), payload)

    def _on_rate_standard_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if self._loading:
            return
        if previous is not None:
            self._commit_standard_rates_into_internal(previous.text().strip())
        if current is None:
            self.ed_rate_values.setPlainText("")
            return
        payload = dict((self._ruleset_data.get("data_rate_policy") or {}).get("by_standard") or {})
        self.ed_rate_values.setPlainText("\n".join(list(payload.get(current.text().strip()) or [])))

    def _on_contract_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if self._loading:
            return
        if current is None:
            self._load_contract_payload("", {})
            return
        payload = dict((self._ruleset_data.get("test_contracts") or {}).get(current.text().strip()) or {})
        self._load_contract_payload(current.text().strip(), payload)

    def _load_selected_dimension(self, row: int) -> None:
        dimensions = dict((self._ruleset_data.get("case_dimensions") or {}).get("dimensions") or {})
        if row < 0 or row >= len(dimensions):
            self._load_dimension_payload("", {})
            return
        name = list(dimensions.keys())[row]
        self._load_dimension_payload(name, dict(dimensions.get(name) or {}))

    def _load_selected_band_psd_policy(self, row: int) -> None:
        bands = dict(self._ruleset_data.get("bands") or {})
        if row < 0 or row >= len(bands):
            self._load_band_psd_payload("", {})
            return
        name = list(bands.keys())[row]
        self._load_band_psd_payload(name, dict(bands.get(name) or {}))

    def _load_selected_standard_rates(self, row: int) -> None:
        by_standard = dict((self._ruleset_data.get("data_rate_policy") or {}).get("by_standard") or {})
        if row < 0 or row >= len(by_standard):
            self.ed_rate_values.setPlainText("")
            return
        name = list(by_standard.keys())[row]
        self.ed_rate_values.setPlainText("\n".join(list(by_standard.get(name) or [])))

    def _load_selected_contract(self, row: int) -> None:
        contracts = dict(self._ruleset_data.get("test_contracts") or {})
        if row < 0 or row >= len(contracts):
            self._load_contract_payload("", {})
            return
        name = list(contracts.keys())[row]
        self._load_contract_payload(name, dict(contracts.get(name) or {}))

    def _load_dimension_payload(self, name: str, payload: Dict[str, Any]) -> None:
        self.ed_dimension_name.setText(name)
        self.cb_dimension_type.setCurrentText(str(payload.get("type", "enum") or "enum"))
        self.ed_dimension_source.setText(str(payload.get("source", "") or ""))
        self.ed_dimension_maps_to.setText(str(payload.get("maps_to", "") or ""))
        self.chk_dimension_optional.setChecked(bool(payload.get("optional", False)))
        self._set_checked_test_types(self.dimension_apply_to_checks, list(payload.get("apply_to") or []))
        self.cb_dimension_non_applicable_mode.setCurrentText(str(payload.get("non_applicable_mode", "OMIT") or "OMIT"))
        self._fill_table(self.dimension_values_table, [{"value": value} for value in list(payload.get("values") or [])], ("value",))

    def _load_band_psd_payload(self, name: str, payload: Dict[str, Any]) -> None:
        normalized = normalize_psd_policy(payload)
        self.cb_psd_method.setCurrentText(str(normalized.get("method", "MARKER_PEAK") or "MARKER_PEAK"))
        self.cb_psd_result_unit.setCurrentText(str(normalized.get("result_unit", "MW_PER_MHZ") or "MW_PER_MHZ"))
        self.cb_psd_comparator.setCurrentText(str(normalized.get("comparator", "upper_limit") or "upper_limit"))
        limit = dict(normalized.get("limit") or {})
        self.ed_psd_limit_value.setText("" if limit.get("value") in (None, "") else str(limit.get("value")))
        self.cb_psd_limit_unit.setCurrentText(str(limit.get("unit", normalized.get("result_unit", "MW_PER_MHZ")) or "MW_PER_MHZ"))
        legacy = dict(normalized.get("legacy_fields_present") or {})
        self.lb_psd_legacy_note.setText(
            f"Band: {name or '(none)'} | psd_policy={legacy.get('psd_policy', False)} | legacy_psd={legacy.get('psd', False)} | legacy_result_unit={legacy.get('psd_result_unit', False)}"
        )

    def _load_contract_payload(self, name: str, payload: Dict[str, Any]) -> None:
        test_id = normalize_test_id(name or payload.get("canonical_test_id") or payload.get("apply_to_test_type"))
        contract_payload = build_test_contract_projection(test_id, self._ruleset_data.get("test_contracts") or {}) if test_id else {}
        pool_item = get_test_item_definition(test_id) or {}
        self.lb_contract_name.setText(str(contract_payload.get("name") or canonical_test_label(test_id)))
        self.lb_contract_test_id.setText(test_id)
        self.lb_contract_measurement_class.setText(str(contract_payload.get("measurement_class", "") or ""))
        self.lb_contract_default_profile_ref.setText(str(contract_payload.get("default_profile_ref", "") or ""))
        self.lb_contract_required_instruments.setText(", ".join(list(contract_payload.get("required_instruments") or [])))
        self.lb_contract_result_fields.setText(", ".join(list(contract_payload.get("result_fields") or [])))
        self.lb_contract_verdict_type.setText(str(contract_payload.get("verdict_type", "") or ""))
        self.lb_contract_procedure_key.setText(str(pool_item.get("procedure_key") or ""))
        self._rebuild_contract_band_checks(test_id)

    def _show_validation_results(self, validation: Dict[str, List[Dict[str, str]]]) -> None:
        self.validation_list.clear()
        self.basic_validation_list.clear()
        for item in validation.get("errors", []):
            text = (
                f"[ERROR] [{self._validation_tab_name_for_path(item.get('path', ''))}] "
                f"{item.get('path', '')}: {item.get('message', '')}"
            )
            row = QListWidgetItem(text, self.validation_list)
            payload = {"path": item.get("path", ""), "severity": "error"}
            row.setData(Qt.UserRole, payload)
            basic_row = QListWidgetItem(text, self.basic_validation_list)
            basic_row.setData(Qt.UserRole, payload)
        for item in validation.get("warnings", []):
            text = (
                f"[WARN] [{self._validation_tab_name_for_path(item.get('path', ''))}] "
                f"{item.get('path', '')}: {item.get('message', '')}"
            )
            row = QListWidgetItem(text, self.validation_list)
            payload = {"path": item.get("path", ""), "severity": "warning"}
            row.setData(Qt.UserRole, payload)
            basic_row = QListWidgetItem(text, self.basic_validation_list)
            basic_row.setData(Qt.UserRole, payload)
        if self.validation_list.count() == 0:
            QListWidgetItem("[OK] No validation issues detected.", self.validation_list)
            QListWidgetItem("[OK] No validation issues detected.", self.basic_validation_list)

    def _reload_preview_filters(self, tests: List[str]) -> None:
        current_test = str(self.cb_preview_test_filter.currentData() or "")
        self.cb_preview_test_filter.blockSignals(True)
        self.cb_preview_test_filter.clear()
        self.cb_preview_test_filter.addItem("All Tests", "")
        for test_name in tests:
            self.cb_preview_test_filter.addItem(test_name, test_name)
        idx = self.cb_preview_test_filter.findData(current_test)
        self.cb_preview_test_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_preview_test_filter.blockSignals(False)

    def _render_preview_summary(self, analysis: Dict[str, Any]) -> None:
        summary = dict(analysis.get("summary") or {})
        optional_axes = list(summary.get("optional_axis_impact") or [])
        axis_multiplier_map = {str(item.get("axis", "")).strip(): str(item.get("multiplier_text", "x1")) for item in optional_axes}
        lines = [
            f"Base Case Count: {summary.get('base_case_count', 0)}",
            f"Data Rate Multiplier: {axis_multiplier_map.get('data_rate', 'x1')}",
            f"Voltage Multiplier: {axis_multiplier_map.get('voltage', 'x1')}",
            f"Total Cases: {summary.get('total_cases', 0)}",
            f"Rendered Sample Rows: {summary.get('rendered_rows', 0)} / {summary.get('sample_limit', PREVIEW_RENDER_LIMIT)}",
            "",
            "Optional Axis Impact:",
        ]
        if optional_axes:
            for item in optional_axes:
                lines.extend(
                    [
                        f"- {item.get('axis', '')}: {item.get('status', '')}",
                        f"  Apply To: {item.get('apply_to_text', '(all tests)')}",
                        f"  Multiplier: {item.get('multiplier_text', 'x1')}",
                        f"  Applied Base Cases: {item.get('applied_base_cases', 0)}",
                        f"  Additional Cases: {item.get('additional_cases', 0)}",
                    ]
                )
        else:
            lines.append("- No optional axes are active.")
        lines.extend(
            [
                "",
                "Explanation:",
                "This preview is built from base axes first, then optional axes are multiplied in only when apply_to and policy conditions allow them.",
            ]
        )
        self.preview_summary.setPlainText("\n".join(lines))
        self.lb_preview_explanation.setText(
            str(summary.get("explanation", "This preview is built from base axes plus optional axis combinations."))
        )

    def _render_axis_breakdown(self, rows: List[Dict[str, Any]]) -> None:
        self.axis_breakdown_table.setRowCount(0)
        for payload in rows:
            row = self.axis_breakdown_table.rowCount()
            self.axis_breakdown_table.insertRow(row)
            self.axis_breakdown_table.setItem(row, 0, QTableWidgetItem(str(payload.get("axis", ""))))
            self.axis_breakdown_table.setItem(row, 1, QTableWidgetItem(str(payload.get("type", ""))))
            self.axis_breakdown_table.setItem(row, 2, QTableWidgetItem(str(payload.get("source", ""))))
            self.axis_breakdown_table.setItem(row, 3, QTableWidgetItem(str(payload.get("apply_to_text", ""))))
            self.axis_breakdown_table.setItem(row, 4, QTableWidgetItem(str(payload.get("non_applicable_mode", ""))))
            self.axis_breakdown_table.setItem(row, 5, QTableWidgetItem(str(payload.get("resolved_values_text", ""))))
            self.axis_breakdown_table.setItem(row, 6, QTableWidgetItem(str(payload.get("impact_text", ""))))

    def _apply_preview_filters(self) -> None:
        rows = list(self._preview_rows or [])
        selected_test = str(self.cb_preview_test_filter.currentData() or "")
        axis_filter = str(self.cb_preview_axis_filter.currentData() or "")
        only_expanded = self.chk_preview_expanded_only.isChecked()
        filtered: List[Dict[str, Any]] = []
        for row in rows:
            if selected_test and str(row.get("test", "")) != selected_test:
                continue
            if axis_filter == "data_rate" and not str(row.get("data_rate", "")).strip():
                continue
            if axis_filter == "voltage" and not str(row.get("voltage_condition", "")).strip():
                continue
            if only_expanded and not bool(row.get("expanded", False)):
                continue
            filtered.append(row)
        self._render_preview_cases(filtered, total_count=len(rows))

    def _render_preview_cases(self, rows: List[Dict[str, Any]], *, total_count: int | None = None) -> None:
        self.preview_case_table.setRowCount(0)
        for row_payload in rows[:PREVIEW_RENDER_LIMIT]:
            row = self.preview_case_table.rowCount()
            self.preview_case_table.insertRow(row)
            self.preview_case_table.setItem(row, 0, QTableWidgetItem(str(row_payload.get("test", ""))))
            self.preview_case_table.setItem(row, 1, QTableWidgetItem(str(row_payload.get("standard", ""))))
            self.preview_case_table.setItem(row, 2, QTableWidgetItem(str(row_payload.get("band", ""))))
            self.preview_case_table.setItem(row, 3, QTableWidgetItem(str(row_payload.get("channel", ""))))
            self.preview_case_table.setItem(row, 4, QTableWidgetItem(str(row_payload.get("bandwidth", ""))))
            self.preview_case_table.setItem(row, 5, QTableWidgetItem(str(row_payload.get("data_rate", ""))))
            self.preview_case_table.setItem(row, 6, QTableWidgetItem(str(row_payload.get("voltage_condition", ""))))
            self.preview_case_table.setItem(row, 7, QTableWidgetItem(str(row_payload.get("target_voltage_v", ""))))
        actual_total = len(rows)
        source_total = total_count if total_count is not None else actual_total
        displayed = min(actual_total, PREVIEW_RENDER_LIMIT)
        self.lb_preview_count.setText(
            f"Preview Cases: {actual_total} filtered / {source_total} source rows | showing {displayed}"
        )

    def _refresh_json_preview(self, data: Dict[str, Any]) -> None:
        self.json_preview.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if self._applying_visual_polish:
            return
        if event.type() in (QEvent.PaletteChange, QEvent.ApplicationPaletteChange):
            self._apply_visual_polish()

    def _connect_live_feedback_signals(self) -> None:
        line_edits = [
            self.ed_ruleset_id,
            self.ed_ruleset_version,
            self.ed_regulation,
            self.ed_tech,
            self.ed_schema_version,
            self.ed_dimension_name,
            self.ed_dimension_source,
            self.ed_dimension_maps_to,
            self.ed_psd_limit_value,
        ]
        for widget in line_edits:
            widget.textChanged.connect(self._on_editor_content_changed)

        combo_boxes = [
            self.cb_ui_mode,
            self.cb_basic_standard,
            self.cb_basic_band,
            self.cb_basic_channel_group,
            self.cb_dimension_type,
            self.cb_dimension_non_applicable_mode,
            self.cb_psd_method,
            self.cb_psd_result_unit,
            self.cb_psd_comparator,
            self.cb_psd_limit_unit,
        ]
        for widget in combo_boxes:
            widget.currentTextChanged.connect(self._on_editor_content_changed)

        plain_text_edits = [self.ed_rate_values]
        for widget in plain_text_edits:
            widget.textChanged.connect(self._on_editor_content_changed)

        check_groups = [
            self.basic_apply_to_checks,
            self.dimension_apply_to_checks,
            self.voltage_apply_to_checks,
            self.data_rate_apply_to_checks,
        ]
        for group in check_groups:
            for widget in group.values():
                widget.toggled.connect(self._on_editor_content_changed)

        direct_checks = [
            self.chk_dimension_optional,
            self.chk_voltage_enabled,
            self.chk_basic_data_rate,
            self.chk_basic_voltage,
            self.chk_basic_temperature,
            self.chk_basic_power_mode,
            self.chk_basic_voltage_nominal,
            self.chk_basic_voltage_high,
            self.chk_basic_voltage_low,
        ]
        for widget in direct_checks:
            widget.toggled.connect(self._on_editor_content_changed)

        for table in (self.dimension_values_table, self.voltage_levels_table):
            table.itemChanged.connect(self._on_editor_content_changed)

    def _on_editor_content_changed(self, *_args) -> None:
        if self._loading:
            return
        self._run_live_feedback()

    def _run_live_feedback(self) -> None:
        if self._loading:
            return
        try:
            data = self.collect_ruleset_data()
        except Exception as exc:
            self._show_validation_results({
                "errors": [{"path": "editor", "message": str(exc)}],
                "warnings": [],
            })
            return
        self._sync_basic_voltage_level_labels(
            self._collect_table_rows(self.voltage_levels_table, ("name", "label", "percent_offset"))
        )
        self._reload_basic_mode_controls(data)
        validation = validate_ruleset_payload(data)
        self._show_validation_results(validation)
        self._apply_field_validation(validation)
        analysis = self._build_preview_analysis(data)
        self._preview_analysis = analysis
        self._preview_rows = list(analysis.get("rows") or [])
        self._refresh_basic_preview(data, analysis, validation)
        self._render_preview_summary(analysis)
        self._render_axis_breakdown(list(analysis.get("axis_breakdown") or []))
        self._reload_preview_filters(list(analysis.get("tests") or []))
        self._apply_preview_filters()
        self._apply_preview_validation_style(validation)
        self._refresh_json_preview(data)

    def calculate_case_summary(self, data: Dict[str, Any]) -> Dict[str, Any]:
        analysis = self._build_preview_analysis(data)
        filtered_rows = self.generate_sample_cases(data)
        filtered_total = len(filtered_rows)
        filtered_base = len(
            [
                row for row in filtered_rows
                if not str(row.get("data_rate", "")).strip()
                and not str(row.get("voltage_condition", "")).strip()
            ]
        )
        voltage_values = {
            str(row.get("voltage_condition", "")).strip()
            for row in filtered_rows
            if str(row.get("voltage_condition", "")).strip()
        }
        rate_values = {
            str(row.get("data_rate", "")).strip()
            for row in filtered_rows
            if str(row.get("data_rate", "")).strip()
        }
        return {
            "base_cases": filtered_base or int((analysis.get("summary") or {}).get("base_case_count", 0)),
            "data_rate_multiplier": f"x{max(len(rate_values), 1)}",
            "voltage_multiplier": f"x{max(len(voltage_values), 1)}",
            "total_cases": filtered_total,
        }

    def generate_sample_cases(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        analysis = self._build_preview_analysis(data)
        return list(self._filter_basic_preview_rows(list(analysis.get("rows") or [])))

    def _refresh_basic_preview(
        self,
        data: Dict[str, Any],
        analysis: Dict[str, Any],
        validation: Dict[str, List[Dict[str, str]]],
    ) -> None:
        summary = self.calculate_case_summary(data)
        rows = self._filter_basic_preview_rows(list(analysis.get("rows") or []))
        self.lb_basic_base_cases.setText(f"Base Cases: {summary.get('base_cases', 0)}")
        self.lb_basic_data_rate_multiplier.setText(
            f"Data Rate Multiplier: {summary.get('data_rate_multiplier', 'x1')}"
        )
        self.lb_basic_voltage_multiplier.setText(
            f"Voltage Multiplier: {summary.get('voltage_multiplier', 'x1')}"
        )
        self.lb_basic_total_cases.setText(f"Total Cases: {summary.get('total_cases', 0)}")

        self.basic_voltage_card.setVisible(self.chk_basic_voltage.isChecked())
        self.basic_sample_table.setRowCount(0)
        for row_payload in rows[:PREVIEW_RENDER_LIMIT]:
            row = self.basic_sample_table.rowCount()
            self.basic_sample_table.insertRow(row)
            self.basic_sample_table.setItem(row, 0, QTableWidgetItem(str(row_payload.get("standard", ""))))
            self.basic_sample_table.setItem(row, 1, QTableWidgetItem(str(row_payload.get("band", ""))))
            self.basic_sample_table.setItem(row, 2, QTableWidgetItem(str(row_payload.get("channel", ""))))
            self.basic_sample_table.setItem(row, 3, QTableWidgetItem(str(row_payload.get("data_rate", ""))))
            self.basic_sample_table.setItem(row, 4, QTableWidgetItem(str(row_payload.get("voltage_condition", ""))))

        colors = self._semantic_colors()
        border_color = (
            colors["error"] if validation.get("errors")
            else colors["warning"] if validation.get("warnings")
            else colors["ok_border"]
        )
        self.basic_sample_table.setStyleSheet(
            "QTableWidget {"
            f"border: 1px solid {border_color};"
            "border-radius: 8px;"
            "}"
        )

    def _filter_basic_preview_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        selected_band = str(self.cb_basic_band.currentData() or "").strip()
        selected_standard = str(self.cb_basic_standard.currentData() or "").strip()
        selected_group = str(self.cb_basic_channel_group.currentData() or "").strip()
        group_channels = set(self._selected_basic_group_channels(selected_band, selected_group))

        filtered: List[Dict[str, Any]] = []
        for row in rows:
            if selected_band and str(row.get("band", "")).strip() != selected_band:
                continue
            if selected_standard and str(row.get("standard", "")).strip() != selected_standard:
                continue
            if group_channels:
                try:
                    channel_value = int(row.get("channel"))
                except Exception:
                    continue
                if channel_value not in group_channels:
                    continue
            filtered.append(row)
        return filtered

    def _selected_basic_group_channels(self, band_name: str, group_name: str) -> List[int]:
        if not band_name or not group_name:
            return []
        band_payload = dict((self._ruleset_data.get("bands") or {}).get(band_name) or {})
        group_payload = dict((band_payload.get("channel_groups") or {}).get(group_name) or {})
        channels: List[int] = []
        for value in list(group_payload.get("channels") or []):
            try:
                channels.append(int(value))
            except Exception:
                continue
        representatives = dict(group_payload.get("representatives") or {})
        for value in representatives.values():
            try:
                ivalue = int(value)
            except Exception:
                continue
            if ivalue not in channels:
                channels.append(ivalue)
        return channels

    def _clear_field_validation(self) -> None:
        for widget in self._validation_styled_widgets:
            widget.setStyleSheet("")
        self._validation_styled_widgets = []

    def _apply_field_validation(self, validation: Dict[str, List[Dict[str, str]]]) -> None:
        self._clear_field_validation()
        messages_by_widget: Dict[QWidget, Dict[str, List[str]]] = {}
        for severity, items in (("error", validation.get("errors", [])), ("warning", validation.get("warnings", []))):
            for item in items:
                path = str(item.get("path", "") or "")
                message = str(item.get("message", "") or "")
                for widget in self._widgets_for_validation_path(path):
                    bucket = messages_by_widget.setdefault(widget, {"error": [], "warning": []})
                    bucket[severity].append(message)

        for widget, grouped in messages_by_widget.items():
            severity = "error" if grouped["error"] else "warning"
            messages = grouped["error"] or grouped["warning"]
            colors = self._semantic_colors()
            color = colors["error"] if severity == "error" else colors["warning"]
            widget.setStyleSheet(
                "QWidget {"
                f"border: 1px solid {color};"
                "border-radius: 4px;"
                "}"
            )
            widget.setToolTip("\n".join(messages))
            self._validation_styled_widgets.append(widget)

    def _apply_preview_validation_style(self, validation: Dict[str, List[Dict[str, str]]]) -> None:
        has_errors = bool(validation.get("errors"))
        has_warnings = bool(validation.get("warnings"))
        colors = self._semantic_colors()
        if has_errors:
            border_color = colors["error"]
            note = "Preview highlighted because validation errors exist."
        elif has_warnings:
            border_color = colors["warning"]
            note = "Preview highlighted because validation warnings exist."
        else:
            border_color = colors["ok_border"]
            note = "Each preview row is generated from base axes plus optional axis combinations. Use the summary and breakdown below to understand why case counts grow."
        self.preview_case_table.setStyleSheet(
            "QTableWidget {"
            f"border: 1px solid {border_color};"
            "border-radius: 6px;"
            "}"
        )
        self.axis_breakdown_table.setStyleSheet(
            "QTableWidget {"
            f"border: 1px solid {border_color};"
            "border-radius: 6px;"
            "}"
        )
        self.lb_preview_explanation.setText(note)

    def _validation_tab_name_for_path(self, path: str) -> str:
        normalized = str(path or "").strip()
        if normalized.startswith("bands."):
            return "PSD Policy"
        if normalized.startswith("voltage_policy"):
            return "Voltage Policy"
        if normalized.startswith("data_rate_policy"):
            return "Data Rate Policy"
        if normalized.startswith("test_contracts."):
            return "Test Contracts"
        if normalized.startswith("case_dimensions."):
            return "Case Dimensions"
        return "General"

    def _widgets_for_validation_path(self, path: str) -> List[QWidget]:
        normalized = str(path or "").strip()
        widgets: List[QWidget] = []
        if normalized.startswith("bands."):
            widgets.append(self.band_list)
            if normalized.endswith(".psd_policy.method"):
                widgets.append(self.cb_psd_method)
            elif normalized.endswith(".psd_policy.result_unit"):
                widgets.append(self.cb_psd_result_unit)
            elif normalized.endswith(".psd_policy.limit.value"):
                widgets.append(self.ed_psd_limit_value)
            elif normalized.endswith(".psd_policy.limit.unit"):
                widgets.append(self.cb_psd_limit_unit)
            return widgets
        if normalized.startswith("voltage_policy"):
            widgets.append(self.voltage_levels_table)
            widgets.append(self.chk_basic_voltage)
            widgets.extend([self.chk_basic_voltage_nominal, self.chk_basic_voltage_high, self.chk_basic_voltage_low])
            if normalized.endswith(".apply_to"):
                widgets.extend(self.voltage_apply_to_checks.values())
                widgets.extend(self.basic_apply_to_checks.values())
            return widgets
        if normalized.startswith("data_rate_policy"):
            widgets.append(self.rate_standard_list)
            widgets.append(self.ed_rate_values)
            widgets.append(self.chk_basic_data_rate)
            if normalized.endswith(".apply_to"):
                widgets.extend(self.data_rate_apply_to_checks.values())
                widgets.extend(self.basic_apply_to_checks.values())
            return widgets
        if normalized.startswith("test_contracts."):
            widgets.append(self.contract_list)
            widgets.extend(self.contract_band_checks.values())
            return widgets
        if normalized.startswith("case_dimensions.dimensions."):
            widgets.append(self.dimension_list)
            if normalized.startswith("case_dimensions.dimensions.standard"):
                widgets.append(self.cb_basic_standard)
            elif normalized.startswith("case_dimensions.dimensions.frequency_band"):
                widgets.append(self.cb_basic_band)
            elif normalized.startswith("case_dimensions.dimensions.channel"):
                widgets.append(self.cb_basic_channel_group)
            if normalized.endswith(".type"):
                widgets.append(self.cb_dimension_type)
            elif normalized.endswith(".source"):
                widgets.append(self.ed_dimension_source)
            elif normalized.endswith(".maps_to"):
                widgets.append(self.ed_dimension_maps_to)
            elif normalized.endswith(".apply_to"):
                widgets.extend(self.dimension_apply_to_checks.values())
            elif normalized.endswith(".values"):
                widgets.append(self.dimension_values_table)
            else:
                widgets.extend([self.ed_dimension_name, self.cb_dimension_type, self.ed_dimension_source, self.ed_dimension_maps_to])
            return widgets
        if normalized in {"id", "version", "regulation", "tech", "schema_version"}:
            mapping = {
                "id": self.ed_ruleset_id,
                "version": self.ed_ruleset_version,
                "regulation": self.ed_regulation,
                "tech": self.ed_tech,
                "schema_version": self.ed_schema_version,
            }
            return [mapping[normalized]]
        return widgets

    def _on_validation_item_clicked(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.UserRole) or {}
        path = str(payload.get("path", "") or "")
        if not path:
            return
        self._navigate_to_validation_path(path)

    def _navigate_to_validation_path(self, path: str) -> None:
        normalized = str(path or "").strip()
        if normalized.startswith("bands."):
            parts = normalized.split(".")
            if len(parts) >= 2:
                self._select_list_item(self.band_list, parts[1])
            self.tabs.setCurrentIndex(self.SECTION_TABS.index("PSD Policy"))
        elif normalized.startswith("voltage_policy"):
            self.tabs.setCurrentIndex(self.SECTION_TABS.index("Voltage Policy"))
        elif normalized.startswith("data_rate_policy.by_standard."):
            parts = normalized.split(".")
            if len(parts) >= 3:
                self._select_list_item(self.rate_standard_list, parts[2])
            self.tabs.setCurrentIndex(self.SECTION_TABS.index("Data Rate Policy"))
        elif normalized.startswith("data_rate_policy"):
            self.tabs.setCurrentIndex(self.SECTION_TABS.index("Data Rate Policy"))
        elif normalized.startswith("test_contracts."):
            parts = normalized.split(".")
            if len(parts) >= 2:
                self._select_list_item(self.contract_list, parts[1])
            self.tabs.setCurrentIndex(self.SECTION_TABS.index("Test Contracts"))
        elif normalized.startswith("case_dimensions.dimensions."):
            parts = normalized.split(".")
            if len(parts) >= 3:
                self._select_list_item(self.dimension_list, parts[2])
            self.tabs.setCurrentIndex(self.SECTION_TABS.index("Case Dimensions"))
        else:
            self.tabs.setCurrentIndex(self.SECTION_TABS.index("General"))

    def _build_preview_analysis(self, data: Dict[str, Any]) -> Dict[str, Any]:
        bands = dict(data.get("bands") or {})
        data_rate_policy = normalize_data_rate_policy(data.get("data_rate_policy") or {})
        voltage_policy = normalize_voltage_policy(data.get("voltage_policy") or {})
        case_dimensions = normalize_case_dimensions(data.get("case_dimensions") or {})
        dimensions = dict(case_dimensions.get("dimensions") or {})
        extra_axis_defs = {
            name: axis_def
            for name, axis_def in dimensions.items()
            if name not in {"frequency_band", "standard", "bandwidth", "channel", "data_rate", "voltage"}
        }
        rows: List[Dict[str, Any]] = []
        axis_multiplier_samples: Dict[str, List[int]] = {}
        tests_seen: set[str] = set()
        base_case_count = 0
        total_case_count = 0
        for band_name, band_payload in bands.items():
            if not isinstance(band_payload, dict):
                continue
            standards = [str(item).strip() for item in (band_payload.get("standards") or []) if str(item).strip()] or [""]
            tests = [str(item).strip().upper() for item in (band_payload.get("tests_supported") or []) if str(item).strip()] or [""]
            channels = self._preview_channels_for_band(band_payload)
            bandwidths = self._preview_bandwidths_for_band(band_payload, dimensions)
            for standard in standards:
                for test_type in tests:
                    tests_seen.add(test_type)
                    data_rates = self._preview_data_rates(data_rate_policy, standard, test_type)
                    voltages = self._preview_voltage_conditions(voltage_policy, test_type)
                    extra_axis_values = self._preview_extra_axis_values(extra_axis_defs, test_type)
                    axis_multiplier_samples.setdefault("data_rate", []).append(max(len(data_rates), 1))
                    axis_multiplier_samples.setdefault("voltage", []).append(max(len(voltages), 1))
                    for axis_name, values in extra_axis_values.items():
                        axis_multiplier_samples.setdefault(axis_name, []).append(max(len(values), 1))
                    for bandwidth in bandwidths:
                        for channel in channels:
                            base_case_count += 1
                            base_multiplier = max(len(data_rates), 1) * max(len(voltages), 1)
                            for values in extra_axis_values.values():
                                base_multiplier *= max(len(values), 1)
                            total_case_count += max(base_multiplier, 1)
                            for data_rate in data_rates:
                                for voltage in voltages:
                                    extra_combinations = self._preview_extra_axis_product(extra_axis_values)
                                    for extra_combination in extra_combinations:
                                        if len(rows) < PREVIEW_GENERATION_LIMIT:
                                            rows.append({
                                                "test": test_type,
                                                "standard": standard,
                                                "band": band_name,
                                                "channel": channel,
                                                "bandwidth": bandwidth,
                                                "data_rate": data_rate.get("value", ""),
                                                "voltage_condition": voltage.get("name", ""),
                                                "target_voltage_v": voltage.get("target_voltage_v", ""),
                                                "expanded": self._preview_row_is_expanded(data_rate, voltage, extra_combination),
                                                "extra_axes": dict(extra_combination),
                                            })
        summary = self._build_preview_summary(
            data=data,
            case_dimensions=case_dimensions,
            data_rate_policy=data_rate_policy,
            voltage_policy=voltage_policy,
            extra_axis_defs=extra_axis_defs,
            base_case_count=base_case_count,
            total_case_count=total_case_count,
            rendered_rows=len(rows),
            axis_multiplier_samples=axis_multiplier_samples,
        )
        axis_breakdown = self._build_axis_breakdown(
            data=data,
            case_dimensions=case_dimensions,
            data_rate_policy=data_rate_policy,
            voltage_policy=voltage_policy,
            extra_axis_defs=extra_axis_defs,
            axis_multiplier_samples=axis_multiplier_samples,
        )
        return {
            "summary": summary,
            "axis_breakdown": axis_breakdown,
            "rows": rows,
            "tests": sorted(tests_seen),
        }

    def _build_preview_cases(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return list((self._build_preview_analysis(data)).get("rows") or [])

    def _preview_channels_for_band(self, band_payload: Dict[str, Any]) -> List[int]:
        out: List[int] = []
        for _, group_payload in dict(band_payload.get("channel_groups") or {}).items():
            representatives = dict((group_payload or {}).get("representatives") or {})
            for key in ("LOW", "MID", "HIGH"):
                value = representatives.get(key)
                if value is not None:
                    try:
                        ivalue = int(value)
                    except Exception:
                        continue
                    if ivalue not in out:
                        out.append(ivalue)
            if not representatives:
                for value in list((group_payload or {}).get("channels") or [])[:3]:
                    try:
                        ivalue = int(value)
                    except Exception:
                        continue
                    if ivalue not in out:
                        out.append(ivalue)
        return out or [0]

    def _preview_bandwidths_for_band(self, band_payload: Dict[str, Any], dimensions: Dict[str, Dict[str, Any]]) -> List[int]:
        axis_def = dict(dimensions.get("bandwidth") or {})
        values: List[int] = []
        for item in (axis_def.get("values") or []):
            try:
                values.append(int(item))
            except Exception:
                continue
        if values:
            return sorted(set(values))
        legacy = list(band_payload.get("bandwidths_mhz") or [])
        for item in legacy:
            try:
                values.append(int(item))
            except Exception:
                continue
        return sorted(set(values)) or [20]

    def _preview_data_rates(self, policy: Dict[str, Any], standard: str, test_type: str) -> List[Dict[str, Any]]:
        if not bool(policy.get("enabled")):
            return [{"value": "", "status": "disabled"}]
        apply_to = list(policy.get("apply_to") or [])
        if apply_to and test_type not in apply_to:
            return [{"value": "", "status": "not_applicable_test_type"}]
        rates = list((policy.get("by_standard") or {}).get(standard, []))
        if not rates:
            return [{"value": "", "status": "disabled_no_standard_rates"}]
        return [{"value": str(rate), "status": "enabled"} for rate in rates]

    def _preview_voltage_conditions(self, policy: Dict[str, Any], test_type: str) -> List[Dict[str, Any]]:
        if not bool(policy.get("enabled")):
            return [{"name": "", "status": "disabled", "target_voltage_v": "(preset nominal required)"}]
        apply_to = list(policy.get("apply_to") or [])
        if apply_to and test_type not in apply_to:
            return [{"name": "", "status": "not_applicable_test_type", "target_voltage_v": ""}]
        levels = list(policy.get("levels") or [])
        if not levels:
            return [{"name": "", "status": "disabled_no_levels", "target_voltage_v": ""}]
        return [
            {
                "name": str(item.get("name", "")).strip().upper(),
                "status": "enabled",
                "target_voltage_v": "(preset nominal required)",
            }
            for item in levels
            if str(item.get("name", "")).strip()
        ] or [{"name": "", "status": "disabled_no_levels", "target_voltage_v": ""}]

    def _preview_extra_axis_values(self, axis_defs: Dict[str, Dict[str, Any]], test_type: str) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for axis_name, axis_def in axis_defs.items():
            apply_to = [str(item).strip().upper() for item in (axis_def.get("apply_to") or []) if str(item).strip()]
            if apply_to and test_type not in apply_to:
                out[axis_name] = [""]
                continue
            if str(axis_def.get("type", "")).strip().lower() == "enum":
                values = [str(item).strip() for item in (axis_def.get("values") or []) if str(item).strip()]
                out[axis_name] = values or [""]
            else:
                out[axis_name] = [""]
        return out

    def _preview_extra_axis_product(self, axis_values: Dict[str, List[str]]) -> List[Dict[str, str]]:
        states: List[Dict[str, str]] = [{}]
        for axis_name, values in axis_values.items():
            next_states: List[Dict[str, str]] = []
            effective_values = list(values or [""])
            for state in states:
                for value in effective_values:
                    merged = dict(state)
                    merged[axis_name] = value
                    next_states.append(merged)
            states = next_states or states
        return states or [{}]

    def _preview_row_is_expanded(
        self,
        data_rate: Dict[str, Any],
        voltage: Dict[str, Any],
        extra_combination: Dict[str, str],
    ) -> bool:
        if str(data_rate.get("value", "")).strip():
            return True
        if str(voltage.get("name", "")).strip():
            return True
        return any(str(value or "").strip() for value in extra_combination.values())

    def _build_preview_summary(
        self,
        *,
        data: Dict[str, Any],
        case_dimensions: Dict[str, Any],
        data_rate_policy: Dict[str, Any],
        voltage_policy: Dict[str, Any],
        extra_axis_defs: Dict[str, Dict[str, Any]],
        base_case_count: int,
        total_case_count: int,
        rendered_rows: int,
        axis_multiplier_samples: Dict[str, List[int]],
    ) -> Dict[str, Any]:
        optional_axes = []
        dimensions = dict(case_dimensions.get("dimensions") or {})
        for axis_name, axis_def in dimensions.items():
            if not bool(axis_def.get("optional")):
                continue
            apply_to = [str(item).strip().upper() for item in (axis_def.get("apply_to") or []) if str(item).strip()]
            multiplier_text = self._format_multiplier_text(axis_multiplier_samples.get(axis_name) or [1])
            max_multiplier = max(axis_multiplier_samples.get(axis_name) or [1])
            additional_cases = base_case_count * max(max_multiplier - 1, 0)
            status = "disabled"
            if axis_name == "data_rate":
                status = "enabled" if bool(data_rate_policy.get("enabled")) else "disabled"
            elif axis_name == "voltage":
                status = "enabled" if bool(voltage_policy.get("enabled")) else "disabled"
            else:
                status = "enabled" if list(axis_def.get("values") or []) else "configured"
            optional_axes.append(
                {
                    "axis": axis_name,
                    "status": status,
                    "apply_to_text": ", ".join(apply_to) if apply_to else "(all tests)",
                    "multiplier_text": multiplier_text,
                    "applied_base_cases": base_case_count if status != "disabled" else 0,
                    "additional_cases": additional_cases if status != "disabled" else 0,
                }
            )
        return {
            "total_cases": total_case_count,
            "rendered_rows": rendered_rows,
            "sample_limit": PREVIEW_RENDER_LIMIT,
            "base_case_count": base_case_count,
            "optional_axis_impact": optional_axes,
            "explanation": (
                "Base cases are built from test, standard, band, bandwidth, and channel. "
                "Optional axes are multiplied in only when their apply_to and policy settings allow them."
            ),
        }

    def _build_axis_breakdown(
        self,
        *,
        data: Dict[str, Any],
        case_dimensions: Dict[str, Any],
        data_rate_policy: Dict[str, Any],
        voltage_policy: Dict[str, Any],
        extra_axis_defs: Dict[str, Dict[str, Any]],
        axis_multiplier_samples: Dict[str, List[int]],
    ) -> List[Dict[str, Any]]:
        dimensions = dict(case_dimensions.get("dimensions") or {})
        bands = dict(data.get("bands") or {})
        all_standards: List[str] = []
        for band_payload in bands.values():
            for item in (dict(band_payload or {}).get("standards") or []):
                value = str(item).strip()
                if value and value not in all_standards:
                    all_standards.append(value)
        rows: List[Dict[str, Any]] = []
        for axis_name, axis_def in dimensions.items():
            axis_type = str(axis_def.get("type", "enum") or "enum")
            source = str(axis_def.get("source", "") or axis_def.get("policy_ref", "") or "")
            apply_to = [str(item).strip().upper() for item in (axis_def.get("apply_to") or []) if str(item).strip()]
            if axis_name == "frequency_band":
                resolved = ", ".join([str(name).strip() for name in bands.keys() if str(name).strip()]) or "(none)"
            elif axis_name == "standard":
                resolved = ", ".join(all_standards) or "(none)"
            elif axis_name == "channel":
                channel_count = sum(len(self._preview_channels_for_band(dict(payload or {}))) for payload in bands.values())
                resolved = f"{channel_count} representative channels"
            elif axis_name == "bandwidth":
                values = []
                for band_payload in bands.values():
                    for bw in self._preview_bandwidths_for_band(dict(band_payload or {}), dimensions):
                        if bw not in values:
                            values.append(bw)
                resolved = ", ".join(str(item) for item in values) or "20"
            elif axis_name == "data_rate":
                samples = []
                for standard, values in dict(data_rate_policy.get("by_standard") or {}).items():
                    if values:
                        samples.append(f"{standard}: {', '.join(list(values)[:4])}")
                    if len(samples) >= 3:
                        break
                resolved = " | ".join(samples) or "(no rate map)"
            elif axis_name == "voltage":
                levels = [str(item.get("name", "")).strip().upper() for item in (voltage_policy.get("levels") or []) if str(item.get("name", "")).strip()]
                resolved = ", ".join(levels) or "(no levels)"
            else:
                values = [str(item).strip() for item in (axis_def.get("values") or []) if str(item).strip()]
                resolved = ", ".join(values) or "(dynamic or empty)"
            rows.append(
                {
                    "axis": axis_name,
                    "type": axis_type,
                    "source": source or "(none)",
                    "apply_to_text": ", ".join(apply_to) if apply_to else "(all tests)",
                    "non_applicable_mode": str(axis_def.get("non_applicable_mode", "OMIT") or "OMIT"),
                    "resolved_values_text": resolved,
                    "impact_text": self._format_multiplier_text(axis_multiplier_samples.get(axis_name) or [1]),
                }
            )
        return rows

    def _format_multiplier_text(self, values: List[int]) -> str:
        clean = sorted({max(int(value), 1) for value in values if value not in (None, "")})
        if not clean:
            return "x1"
        if len(clean) == 1:
            return f"x{clean[0]}"
        return f"x{clean[0]}..x{clean[-1]}"

    def _build_test_type_checkboxes(self) -> Dict[str, QCheckBox]:
        return {name: QCheckBox(name) for name in KNOWN_TEST_TYPES}

    def _wrap_checkbox_grid(self, title: str, checks: Dict[str, QCheckBox]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        if title:
            layout.addWidget(QLabel(title))
        grid = QGridLayout()
        for idx, name in enumerate(KNOWN_TEST_TYPES):
            grid.addWidget(checks[name], idx // 2, idx % 2)
        layout.addLayout(grid)
        return widget

    def _collect_checked_test_types(self, checks: Dict[str, QCheckBox]) -> List[str]:
        return [name for name, checkbox in checks.items() if checkbox.isChecked()]

    def _set_checked_test_types(self, checks: Dict[str, QCheckBox], values: List[str]) -> None:
        normalized = {str(item).strip().upper() for item in values}
        for name, checkbox in checks.items():
            checkbox.setChecked(name in normalized)

    def _collect_table_rows(self, table: QTableWidget, columns: tuple[str, ...]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in range(table.rowCount()):
            payload: Dict[str, Any] = {}
            has_value = False
            for col, key in enumerate(columns):
                item = table.item(row, col)
                value = item.text().strip() if item is not None else ""
                if value:
                    has_value = True
                payload[key] = self._parse_float(value) if key == "percent_offset" else value
            if has_value:
                out.append(payload)
        return out

    def _collect_table_column(self, table: QTableWidget, column: int) -> List[str]:
        out: List[str] = []
        for row in range(table.rowCount()):
            item = table.item(row, column)
            value = item.text().strip() if item is not None else ""
            if value:
                out.append(value)
        return out

    def _fill_table(self, table: QTableWidget, rows: List[Dict[str, Any]], columns: tuple[str, ...]) -> None:
        table.setRowCount(0)
        for payload in rows:
            row = table.rowCount()
            table.insertRow(row)
            for col, key in enumerate(columns):
                value = payload.get(key, "")
                table.setItem(row, col, QTableWidgetItem("" if value in (None, "") else str(value)))

    def _append_empty_row(self, table: QTableWidget) -> None:
        table.insertRow(table.rowCount())

    def _remove_selected_rows(self, table: QTableWidget) -> None:
        selected_rows = sorted({item.row() for item in table.selectedItems()}, reverse=True)
        for row in selected_rows:
            table.removeRow(row)

    def _current_dimension_name(self) -> str:
        item = self.dimension_list.currentItem()
        return item.text().strip() if item else ""

    def _current_band_name(self) -> str:
        item = self.band_list.currentItem()
        return item.text().strip() if item else ""

    def _current_rate_standard(self) -> str:
        item = self.rate_standard_list.currentItem()
        return item.text().strip() if item else ""

    def _current_contract_name(self) -> str:
        item = self.contract_list.currentItem()
        return item.text().strip() if item else ""

    def _select_list_item(self, list_widget: QListWidget, text: str) -> None:
        matches = list_widget.findItems(text, Qt.MatchExactly)
        if matches:
            list_widget.setCurrentItem(matches[0])

    def _parse_csv(self, text: str) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for item in str(text or "").split(","):
            value = item.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def _parse_csv_or_lines(self, text: str, *, uppercase: bool = False) -> List[str]:
        raw = str(text or "").replace(",", "\n")
        out: List[str] = []
        seen: set[str] = set()
        for line in raw.splitlines():
            value = line.strip()
            if uppercase:
                value = value.upper()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def _parse_float(self, text: str) -> float | None:
        value = str(text or "").strip()
        if not value:
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _on_voltage_level_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self._updating_voltage_labels or item is None:
            return
        if item.column() not in (0, 2):
            return

        row = item.row()
        name_item = self.voltage_levels_table.item(row, 0)
        label_item = self.voltage_levels_table.item(row, 1)
        offset_item = self.voltage_levels_table.item(row, 2)
        if name_item is None:
            return
        if label_item is None:
            label_item = QTableWidgetItem("")
            self._updating_voltage_labels = True
            try:
                self.voltage_levels_table.setItem(row, 1, label_item)
            finally:
                self._updating_voltage_labels = False
        if offset_item is None:
            return

        level_name = str(name_item.text() or "").strip().upper()
        current_label = str(label_item.text() or "").strip()
        offset_value = self._parse_float(offset_item.text())
        suggested_label = self._suggest_voltage_label(level_name, offset_value)
        if not suggested_label:
            return
        if current_label and not self._is_auto_voltage_label(level_name, current_label):
            return
        if current_label == suggested_label:
            return

        self._updating_voltage_labels = True
        try:
            label_item.setText(suggested_label)
        finally:
            self._updating_voltage_labels = False
        self._sync_basic_voltage_level_labels(
            self._collect_table_rows(self.voltage_levels_table, ("name", "label", "percent_offset"))
        )

    def _suggest_voltage_label(self, level_name: str, percent_offset: float | None) -> str:
        name = str(level_name or "").strip().upper()
        if name == "NOMINAL":
            return "Nominal"
        if percent_offset is None:
            return ""
        magnitude = abs(float(percent_offset))
        magnitude_text = f"{magnitude:g}%"
        if name == "LOW":
            return f"Low (-{magnitude_text})"
        if name == "HIGH":
            return f"High (+{magnitude_text})"
        return ""

    def _is_auto_voltage_label(self, level_name: str, label_text: str) -> bool:
        label = str(label_text or "").strip()
        if not label:
            return True
        name = str(level_name or "").strip().upper()
        if name == "NOMINAL":
            return label == "Nominal"
        prefix = ""
        if name == "LOW":
            prefix = "Low (-"
        elif name == "HIGH":
            prefix = "High (+"
        else:
            return False
        return label.startswith(prefix) and label.endswith("%)")

    def _next_available_name(self, existing: Any, prefix: str) -> str:
        normalized = {str(item).strip().lower() for item in existing}
        index = 1
        while f"{prefix}_{index}".lower() in normalized:
            index += 1
        return f"{prefix}_{index}"

    def _select_pool_test_items(self, data: Dict[str, Any]) -> tuple[List[str], List[str]]:
        selected = set(collect_ruleset_test_types(data))
        tech = str(data.get("tech", "")).strip().upper()
        selectable_items = list_available_test_items(tech=tech, selectable_only=True)
        candidates = [
            item
            for item in selectable_items
            if item["id"] not in selected
        ]
        if not selectable_items:
            QMessageBox.information(
                self,
                "Add Test Item",
                (
                    "No selectable test items are available for this RuleSet.\n\n"
                    f"RuleSet tech: {tech or '(empty)'}\n"
                    "Check the global test item pool for enabled=true and a valid procedure_key."
                ),
            )
            return [], []
        if not candidates:
            QMessageBox.information(
                self,
                "Add Test Item",
                (
                    "All selectable pool test items are already added to this RuleSet.\n\n"
                    f"Selectable pool items: {', '.join(item['id'] for item in selectable_items)}\n"
                    f"Already added: {', '.join(sorted(selected)) if selected else '(none)'}"
                ),
            )
            return [], []

        available_bands = [str(name).strip() for name in dict(data.get("bands") or {}).keys() if str(name).strip()]
        dialog = AddTestItemFromPoolDialog(
            ruleset_tech=tech,
            available_items=candidates,
            bands=available_bands,
            preselected_band=self._current_band_name(),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return [], []
        selected_test_ids = normalize_test_id_list(dialog.selected_test_ids())
        selected_bands = [str(name).strip() for name in dialog.selected_bands() if str(name).strip()]
        if not selected_test_ids:
            QMessageBox.information(self, "Add Test Item", "Select at least one test item.")
            return [], []
        if available_bands and not selected_bands:
            QMessageBox.information(self, "Add Test Item", "Select at least one band.")
            return [], []
        return selected_test_ids, selected_bands or available_bands

    def _enable_test_items_for_ruleset(self, data: Dict[str, Any], test_ids: List[str], band_names: List[str]) -> Dict[str, Any]:
        updated = deepcopy(data)
        canonical_test_ids = normalize_test_id_list(test_ids)
        target_bands = {str(name).strip() for name in (band_names or []) if str(name).strip()}
        bands = dict(updated.get("bands") or {})
        for band_name, band_payload in bands.items():
            payload = dict(band_payload or {})
            tests_supported = normalize_test_id_list(payload.get("tests_supported") or [])
            if target_bands and band_name not in target_bands:
                payload["tests_supported"] = tests_supported
                bands[band_name] = payload
                continue
            for canonical_test_id in canonical_test_ids:
                if canonical_test_id not in tests_supported:
                    tests_supported.append(canonical_test_id)
            payload["tests_supported"] = tests_supported
            bands[band_name] = payload
        updated["bands"] = bands
        updated["test_contracts"] = project_ruleset_test_contracts(
            updated.get("test_contracts") or {},
            tests_supported=collect_ruleset_test_types(updated),
        )
        return updated

    def _disable_test_item_for_ruleset(self, data: Dict[str, Any], test_id: str) -> Dict[str, Any]:
        updated = deepcopy(data)
        canonical_test_id = normalize_test_id(test_id)
        bands = dict(updated.get("bands") or {})
        for band_name, band_payload in bands.items():
            payload = dict(band_payload or {})
            payload["tests_supported"] = [
                item for item in normalize_test_id_list(payload.get("tests_supported") or [])
                if item != canonical_test_id
            ]
            bands[band_name] = payload
        updated["bands"] = bands
        voltage_policy = dict(updated.get("voltage_policy") or {})
        if list(voltage_policy.get("apply_to") or []):
            voltage_policy["apply_to"] = [
                item for item in normalize_test_id_list(voltage_policy.get("apply_to") or [])
                if item != canonical_test_id
            ]
        updated["voltage_policy"] = voltage_policy

        data_rate_policy = dict(updated.get("data_rate_policy") or {})
        if list(data_rate_policy.get("apply_to") or []):
            data_rate_policy["apply_to"] = [
                item for item in normalize_test_id_list(data_rate_policy.get("apply_to") or [])
                if item != canonical_test_id
            ]
        updated["data_rate_policy"] = data_rate_policy

        case_dimensions = dict(updated.get("case_dimensions") or {})
        dimensions = dict(case_dimensions.get("dimensions") or {})
        for axis_name, axis_payload in dimensions.items():
            payload = dict(axis_payload or {})
            if list(payload.get("apply_to") or []):
                payload["apply_to"] = [
                    item for item in normalize_test_id_list(payload.get("apply_to") or [])
                    if item != canonical_test_id
                ]
            dimensions[axis_name] = payload
        case_dimensions["dimensions"] = dimensions
        updated["case_dimensions"] = normalize_case_dimensions(case_dimensions)
        updated["test_contracts"] = project_ruleset_test_contracts(
            updated.get("test_contracts") or {},
            tests_supported=collect_ruleset_test_types(updated),
        )
        return updated

    def _rebuild_contract_band_checks(self, test_id: str) -> None:
        while self.contract_band_checks_layout.count():
            item = self.contract_band_checks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.contract_band_checks = {}
        if not test_id:
            return
        for band_name, band_payload in dict(self._ruleset_data.get("bands") or {}).items():
            checkbox = QCheckBox(str(band_name))
            checkbox.setChecked(test_id in normalize_test_id_list((band_payload or {}).get("tests_supported") or []))
            checkbox.toggled.connect(lambda checked, band=str(band_name), test=str(test_id): self._on_contract_band_toggled(band, test, checked))
            self.contract_band_checks_layout.addWidget(checkbox)
            self.contract_band_checks[band_name] = checkbox
        self.contract_band_checks_layout.addStretch(1)

    def _on_contract_band_toggled(self, band_name: str, test_id: str, checked: bool) -> None:
        if self._loading:
            return
        data = deepcopy(self.collect_ruleset_data())
        bands = dict(data.get("bands") or {})
        payload = dict(bands.get(band_name) or {})
        tests_supported = normalize_test_id_list(payload.get("tests_supported") or [])
        canonical_test_id = normalize_test_id(test_id)
        if checked and canonical_test_id not in tests_supported:
            tests_supported.append(canonical_test_id)
        if not checked:
            tests_supported = [item for item in tests_supported if item != canonical_test_id]
        payload["tests_supported"] = tests_supported
        bands[band_name] = payload
        data["bands"] = bands
        data["test_contracts"] = project_ruleset_test_contracts(
            data.get("test_contracts") or {},
            tests_supported=collect_ruleset_test_types(data),
        )
        self.load_ruleset_data(data, source_path=self._current_path)
        self._select_list_item(self.contract_list, canonical_test_id)
