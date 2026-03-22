from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QToolBar, QVBoxLayout, QWidget, QTabWidget, QProgressBar
)

from application.plan_service import PlanService
from application.app_state import AppState
from application.settings_store import SettingsStore
from application.device_registry import DeviceRegistry
from application.device_discovery import DeviceDiscovery
from application.equipment_profile_repo import EquipmentProfileRepo
from application.preflight_service import PreflightService
from application.preset_repo import PresetRepo
from ui.table_model import CaseTableModel
from ui.execution_order_dialog import ExecutionOrderDialog
from ui.rf_path_dialog import RFPathDialog
from ui.power_settings_dialog import PowerSettingsDialog
from ui.motion_settings_dialog import MotionSettingsDialog
from ui.tabs.compare_tab import CompareTab
from ui.tabs.results_tab import ResultsTab
from ui.tabs.plan_tab import PlanTab
from ui.tabs.instrument_settings_tab import InstrumentSettingsTab
from ui.tabs.device_manager_tab import DeviceManagerTab
from ui.tabs.equipment_profile_tab import EquipmentProfileTab
from ui.tabs.manual_motion_tab import ManualMotionTab
from ui.plan_context import PlanContext
from ui.controllers import PlanController, RunController, ScenarioController
from ui.dialogs import PresetEditorDialog
import uuid

import json
from datetime import datetime
from PySide6.QtWidgets import QFileDialog





class MainWindow(QMainWindow):
    PAGE_SIZE = 200

    @property
    def project_id(self) -> Optional[str]:
        return self.state.project_id

    @project_id.setter
    def project_id(self, value: Optional[str]) -> None:
        self.state.project_id = value

    @property
    def preset_id(self) -> Optional[str]:
        return self.state.preset_id

    @preset_id.setter
    def preset_id(self, value: Optional[str]) -> None:
        self.state.preset_id = value

    @property
    def _current_plan_node_id(self) -> Optional[str]:
        return self.state.current_plan_node_id

    @_current_plan_node_id.setter
    def _current_plan_node_id(self, value: Optional[str]) -> None:
        self.state.current_plan_node_id = value

    @property
    def _current_filter(self) -> Optional[Dict[str, Any]]:
        return self.state.current_filter

    @_current_filter.setter
    def _current_filter(self, value: Optional[Dict[str, Any]]) -> None:
        self.state.current_filter = value

    @property
    def _current_offset(self) -> int:
        return self.state.current_offset

    @_current_offset.setter
    def _current_offset(self, value: int) -> None:
        self.state.current_offset = value

    def __init__(self, plan_service: PlanService, run_repo, run_service):
        super().__init__()

        self.svc = plan_service
        self.run_repo = run_repo
        self.run_service = run_service

        self.state = AppState()
        self.settings_store = SettingsStore(Path("config/instrument_settings.json"))
        self.device_registry = DeviceRegistry(Path("config/devices.json"))
        self.profile_repo = EquipmentProfileRepo(Path("config/equipment_profiles.json"))
        self.device_discovery = DeviceDiscovery()
        self.preflight_service = PreflightService(
            device_registry=self.device_registry,
            profile_repo=self.profile_repo,
        )
        self.preset_file_repo = PresetRepo(Path("presets"))

        # Bridge runtime managers to shared registries
        self.run_service.instrument_manager.device_registry = self.device_registry
        self.run_service.instrument_manager.profile_repo = self.profile_repo
        self.run_service.instrument_manager.discovery = self.device_discovery

        self._plans: Dict[str, PlanContext] = {}
        self._tree_filter: Optional[Dict[str, Any]] = None
        self._plan_filter_bar: Optional[Dict[str, Any]] = None
        self._current_group_filter: Optional[Dict[str, Any]] = None

        self.setWindowTitle("RF Test Platform (Prototype)")
        self.resize(1200, 800)

        self._run_controller = RunController(self)
        self._scenario_controller = ScenarioController(self)
        self._plan_controller = PlanController(self)

        self._build_ui()
        self._load_initial_data()

        self._worker = None
        self._last_run_id = None
        self._last_results_rows: list[dict] = []

        self._scenario_worker = None
        self._scenario_total_cases = 0
        self._scenario_processed_cases = 0
        self._scenario_run_summaries = []

        self._run_total_cases = 0
        self._run_processed_cases = 0

        self._run_pass_count = 0
        self._run_fail_count = 0
        self._run_skip_count = 0
        self._run_error_count = 0
        self._running_preset_name = ""
        self._running_equipment_profile_name = ""

        


    def _build_ui(self):
        tabs = QTabWidget()

        # shared toolbar widgets
        self.project_combo = QComboBox()
        self.preset_combo = QComboBox()
        self.profile_combo = QComboBox()
        self.btn_refresh_profiles = QPushButton("Refresh Profiles")
        self.btn_preset_editor = QPushButton("Preset Editor")

        self.btn_start = QPushButton("Run Plan")
        self.btn_start.setToolTip("현재 선택된 plan의 전체 runnable 케이스를 실행합니다")
        self.btn_run_scenario = QPushButton("Run Scenario")
        self.btn_stop = QPushButton("Stop")
        self.btn_rerun = QPushButton("Create Re-run (FAIL)")
        self.btn_order = QPushButton("Execution Order")
        self.btn_rf_path = QPushButton("RF Path")
        self.btn_power = QPushButton("Power")
        self.btn_motion = QPushButton("Motion")
        self.btn_plan_summary = QPushButton("Plan Summary")

        self.btn_add_plan = QPushButton("Add Plan")
        self.btn_remove_plan = QPushButton("Remove Plan")
        self.btn_reload = QPushButton("Reload Plan")
        self.btn_more = QPushButton("Load More")
        self.btn_skip = QPushButton("Skip Selected")
        self.btn_skip.setEnabled(False)
        self.btn_skip.setToolTip("Row-level skip is disabled in filter-driven execution mode.")

        self.lbl_status = QLabel("Idle")

        self.progress_run = QProgressBar()
        self.progress_run.setMinimum(0)
        self.progress_run.setMaximum(100)
        self.progress_run.setValue(0)
        self.progress_run.setTextVisible(True)
        self.progress_run.setFormat("Idle")
        self.progress_run.setFixedWidth(260)

        self._build_run_toolbar()
        self.addToolBarBreak()
        self._build_setup_toolbar()
        self.addToolBarBreak()
        self._build_plan_toolbar()

        # toolbar signals
        self.btn_start.clicked.connect(self.on_start_run)
        self.btn_run_scenario.clicked.connect(self.on_start_scenario_run)
        self.btn_stop.clicked.connect(self.on_stop_run)
        self.btn_rerun.clicked.connect(self.on_create_rerun)
        self.btn_order.clicked.connect(self.on_edit_execution_order)
        self.btn_rf_path.clicked.connect(self.on_edit_rf_path)
        self.btn_power.clicked.connect(self.on_edit_power_settings)
        self.btn_motion.clicked.connect(self.on_edit_motion_settings)
        self.btn_plan_summary.clicked.connect(self.on_show_plan_summary)

        self.project_combo.currentIndexChanged.connect(self.on_project_changed)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.btn_refresh_profiles.clicked.connect(self._reload_equipment_profiles)
        self.btn_preset_editor.clicked.connect(self.on_open_preset_editor)

        self.btn_add_plan.clicked.connect(self.on_add_plan)
        self.btn_remove_plan.clicked.connect(self.on_remove_plan_from_scenario)
        self.btn_more.clicked.connect(self.on_load_more)
        self.btn_skip.clicked.connect(self.on_skip_selected)
        self.btn_reload.clicked.connect(self.on_reload_plan)

        self.plan_widget = PlanTab(parent=self)
        self._plan_controller.bind_ui()
        self.tree = self.plan_widget.tree
        self.tree_model = self.plan_widget.tree_model
        self.table = self.plan_widget.table
        self.case_model = self.plan_widget.case_model
        self.group_model = self.plan_widget.group_model
        self.btn_save_scenario = self.plan_widget.btn_save_scenario
        self.btn_load_scenario = self.plan_widget.btn_load_scenario
        self.btn_clear_scenario = self.plan_widget.btn_clear_scenario

        self.tree.clicked.connect(self.on_tree_clicked)
        self.plan_widget.btn_apply_filter.clicked.connect(self.on_apply_plan_filter)
        self.plan_widget.btn_clear_filter.clicked.connect(self.on_clear_plan_filter)
        self.plan_widget.btn_run_filtered.clicked.connect(self.on_run_filtered)
        self.plan_widget.btn_group_drilldown.clicked.connect(self.on_group_drilldown)
        self.plan_widget.group_table.doubleClicked.connect(self.on_group_drilldown)
        self.btn_save_scenario.clicked.connect(self.on_save_scenario)
        self.btn_load_scenario.clicked.connect(self.on_load_scenario)
        self.btn_clear_scenario.clicked.connect(self.on_clear_scenario)

        tabs.addTab(self.plan_widget, "Plan")

        self.results_widget = ResultsTab(
            service=self.svc,
            run_repo=self.run_repo,
            get_project_id=lambda: self.project_id,
            get_base_preset_id=lambda: self.preset_id,
            reload_presets_callback=self._reload_presets,
            parent=self,
        )
        tabs.addTab(self.results_widget, "Results")

        self.compare_widget = CompareTab(service=self.svc, get_project_id=lambda: self.project_id, parent=self)
        tabs.addTab(self.compare_widget, "Compare")

        instrument_settings = self.settings_store.load_instrument_settings()
        self.instrument_widget = InstrumentSettingsTab(
            initial_settings=instrument_settings,
            save_settings_callback=self._save_instrument_settings,
            apply_factory_callback=self._apply_instrument_factory,
            parent=self,
        )
        tabs.addTab(self.instrument_widget, "Instrument")

        self.device_manager_widget = DeviceManagerTab(
            device_registry=self.device_registry,
            instrument_manager=self.run_service.instrument_manager,
            parent=self,
        )
        tabs.addTab(self.device_manager_widget, "Device Manager")

        self.equipment_profile_widget = EquipmentProfileTab(
            profile_repo=self.profile_repo,
            device_registry=self.device_registry,
            parent=self,
        )
        tabs.addTab(self.equipment_profile_widget, "Equipment Profile")

        self.manual_motion_widget = ManualMotionTab(
            instrument_manager=self.run_service.instrument_manager,
            get_equipment_profile_name=self._current_equipment_profile_name,
            store_path=Path("config/manual_motion_positions.json"),
            parent=self,
        )
        tabs.addTab(self.manual_motion_widget, "Manual Motion")

        self.setCentralWidget(tabs)

    def _build_run_toolbar(self):
        toolbar = QToolBar("Run")
        toolbar.setObjectName("run_toolbar")
        self.addToolBar(toolbar)

        toolbar.addWidget(self.btn_start)
        toolbar.addWidget(self.btn_run_scenario)
        toolbar.addWidget(self.btn_stop)
        toolbar.addWidget(self.btn_rerun)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Status: "))
        toolbar.addWidget(self.lbl_status)
        toolbar.addSeparator()
        toolbar.addWidget(self.progress_run)

    def _build_setup_toolbar(self):
        toolbar = QToolBar("Setup")
        toolbar.setObjectName("setup_toolbar")
        self.addToolBar(toolbar)

        toolbar.addWidget(QLabel(" Project: "))
        toolbar.addWidget(self.project_combo)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Preset: "))
        toolbar.addWidget(self.preset_combo)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Equipment: "))
        toolbar.addWidget(self.profile_combo)
        toolbar.addWidget(self.btn_refresh_profiles)
        toolbar.addWidget(self.btn_preset_editor)

    def _build_plan_toolbar(self):
        toolbar = QToolBar("Plan")
        toolbar.setObjectName("plan_toolbar")
        self.addToolBar(toolbar)

        toolbar.addWidget(self.btn_add_plan)
        toolbar.addWidget(self.btn_remove_plan)
        toolbar.addWidget(self.btn_more)
        toolbar.addWidget(self.btn_skip)
        toolbar.addWidget(self.btn_reload)
        toolbar.addSeparator()
        toolbar.addWidget(self.btn_order)
        toolbar.addWidget(self.btn_rf_path)
        toolbar.addWidget(self.btn_power)
        toolbar.addWidget(self.btn_motion)
        toolbar.addWidget(self.btn_plan_summary)
    def _save_instrument_settings(self, settings: Dict[str, Any]) -> None:
        self.settings_store.save_instrument_settings(settings)

    def _apply_instrument_factory(self, factory) -> None:
        try:
            self.run_service.instrument_manager.set_factory(factory)
        except Exception as e:
            QMessageBox.warning(self, "Apply instrument failed", str(e))
            raise

    def _current_antenna(self) -> str | None:
        if hasattr(self, "_plan_controller") and self._plan_controller is not None:
            return self._plan_controller.current_antenna()
        return None

    def _current_plan_meta(self) -> dict:
        if hasattr(self, "_plan_controller") and self._plan_controller is not None:
            try:
                ctx = self._plan_controller._current_context()
                if ctx and getattr(ctx, "recipe", None):
                    return dict(ctx.recipe.meta or {})
            except Exception:
                pass
        return {}

    def _run_display_context(self) -> dict:
        return build_run_display_context(self._current_plan_meta())

    def _antenna_display_suffix(self) -> str:
        return build_status_suffix({"rf_path": {"antenna": get_antenna(self._current_plan_meta())}})

    def _motion_display_suffix(self) -> str:
        motion = get_motion(self._current_plan_meta())
        return (" | " + self._run_display_context().get("motion_text")) if self._run_display_context().get("motion_text") else ""

    def _power_display_suffix(self) -> str:
        return (" | " + self._run_display_context().get("power_text")) if self._run_display_context().get("power_text") else ""

    def _equipment_display_suffix(self) -> str:
        profile_name = self._current_equipment_profile_name()
        if not profile_name:
            return ""
        profile = self.profile_repo.get_profile(profile_name)
        parts = [f"EQ:{profile_name}"]
        analyzer = getattr(profile, "analyzer", None) if profile else None
        if analyzer:
            parts.append(f"AN:{analyzer}")
        return " | " + " | ".join(parts)

    def _equipment_status_suffix(self) -> str:
        profile_name = self._current_equipment_profile_name()
        return f" | EQ:{profile_name}" if profile_name else ""

    def _reload_equipment_profiles(self, select_profile_name: Optional[str] = None):
        self.profile_combo.blockSignals(True)
        current = select_profile_name or self.profile_combo.currentData()
        self.profile_combo.clear()

        profiles = self.profile_repo.list_profiles()
        self.profile_combo.addItem("(None)", None)
        for p in profiles:
            self.profile_combo.addItem(p.name, p.name)

        if current:
            idx = self.profile_combo.findData(current)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)


    def _current_equipment_profile_name(self) -> Optional[str]:
        value = self.profile_combo.currentData()
        return str(value) if value else None

    def _load_initial_data(self):
        project_id = self.svc.ensure_default_project()
        self._reload_projects(select_project_id=project_id)
        self._reload_presets(project_id)

        if self.project_combo.count() > 0 and self.project_combo.currentIndex() < 0:
            self.project_combo.setCurrentIndex(0)
        if self.preset_combo.count() > 0 and self.preset_combo.currentIndex() < 0:
            self.preset_combo.setCurrentIndex(0)

        self.project_id = self.project_combo.currentData()
        self.preset_id = self.preset_combo.currentData()

        self._reload_equipment_profiles()
        if self.project_id:
            self.on_project_changed(self.project_combo.currentIndex())
        else:
            self.project_id = None
            self.preset_id = None

        if self.preset_id:
            self.on_preset_changed(self.preset_combo.currentIndex())
    
    def _reload_projects(self, select_project_id: Optional[str] = None):
        self.project_combo.blockSignals(True)
        self.project_combo.clear()

        projects = self.svc.list_projects()
        for p in projects:
            self.project_combo.addItem(p["name"], userData=p["project_id"])

        self.project_combo.blockSignals(False)

        if select_project_id:
            idx = self.project_combo.findData(select_project_id)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)

    def _reload_presets(self, project_id: str, select_preset_id: Optional[str] = None):
        previous_preset_id = self.preset_combo.currentData()

        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()

        presets = self.svc.list_presets(project_id)
        for pr in presets:
            self.preset_combo.addItem(pr["name"], userData=pr["preset_id"])

        self.preset_combo.blockSignals(False)

        target_id = select_preset_id or previous_preset_id
        idx = self.preset_combo.findData(target_id) if target_id else -1
        if idx < 0 and self.preset_combo.count() > 0:
            idx = 0
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
            self.preset_id = self.preset_combo.currentData()
        else:
            self.preset_id = None

    def on_reload_plan(self):
        self._plan_controller.reload_plan()

    def on_project_changed(self, _idx: int):
        pid = self.project_combo.currentData()
        self.project_id = str(pid) if pid else None

        if self.project_id:
            self._reload_presets(self.project_id)
        else:
            self.preset_combo.blockSignals(True)
            self.preset_combo.clear()
            self.preset_combo.blockSignals(False)
            self.preset_id = None

        self.preset_id = self.preset_combo.currentData()

        # 트리/테이블 reset
        self.tree_model.removeRows(0, self.tree_model.rowCount())
        self.case_model.clear()

        if hasattr(self, "results_widget"):
            try:
                self.results_widget.run_combo.clear()
                self.results_widget.table_model.set_rows([])
                self.results_widget.step_log_model.set_rows([])
                self.results_widget.summary.setText("")
            except Exception:
                pass

        if hasattr(self, "compare_widget"):
            try:
                self.compare_widget.refresh_runs()
                if hasattr(self.compare_widget, "clear_compare"):
                    self.compare_widget.clear_compare()
            except Exception:
                pass

    def on_preset_changed(self, _idx: int):
        self.preset_id = self.preset_combo.currentData()

    def on_open_preset_editor(self):
        dlg = PresetEditorDialog(
            preset_repo=self.preset_file_repo,
            plan_repo=getattr(self.svc, "repo", None),
            project_id=self.project_id,
            parent=self,
        )
        before = {p["preset_id"]: p["name"] for p in (self.svc.list_presets(self.project_id) if self.project_id else [])}
        dlg.exec()
        if self.project_id:
            selected_preset_id = getattr(dlg, "last_imported_project_preset_id", None)
            self._reload_presets(self.project_id, select_preset_id=selected_preset_id)
            after = {p["preset_id"]: p["name"] for p in self.svc.list_presets(self.project_id)}
            if len(after) != len(before):
                new_names = sorted(set(after.values()) - set(before.values()))
                if new_names:
                    self.statusBar().showMessage(f"Imported presets: {', '.join(new_names)}", 5000)

    def on_add_plan(self):
        self._plan_controller.add_plan()

    def _effective_test_order(self, ctx: PlanContext) -> list[str]:
        return self._plan_controller.effective_test_order(ctx)

    def _append_plan_to_tree(self, plan_id: str, ctx: PlanContext) -> QStandardItem:
        return self._plan_controller.append_plan_to_tree(plan_id, ctx)

    def _refresh_plan_tree_order_only(self, plan_id: str, selected_test_type: str | None = None) -> bool:
        return self._plan_controller.refresh_plan_tree_order_only(plan_id, selected_test_type)

    def _clear_cases_view(self):
        self._plan_controller.clear_cases_view()

    def _legacy__get_selected_result_filters(self) -> dict:
        return {
            "status": self.result_filter_status.currentText(),
            "test_type": self.result_filter_test_type.currentText(),
            "band": self.result_filter_band.currentText(),
            "standard": self.result_filter_standard.currentText(),
            "bw_mhz": self.result_filter_bw.currentText(),
            "channel": self.result_filter_channel.currentText(),
            "search": self.result_search.text().strip().lower(),
        }

    def _legacy__apply_result_filters(self, rows: list[dict], filters: dict) -> list[dict]:
        filtered = []

        for r in rows:
            if filters["test_type"] != "ALL" and str(r.get("test_type", "")) != filters["test_type"]:
                continue
            if filters["band"] != "ALL" and str(r.get("band", "")) != filters["band"]:
                continue
            if filters["standard"] != "ALL" and str(r.get("standard", "")) != filters["standard"]:
                continue
            if filters["bw_mhz"] != "ALL" and str(r.get("bw_mhz", "")) != filters["bw_mhz"]:
                continue
            if filters["channel"] != "ALL" and str(r.get("channel", "")) != filters["channel"]:
                continue

            search_text = filters["search"]
            if search_text:
                hay = " ".join([
                    str(r.get("test_type", "")),
                    str(r.get("band", "")),
                    str(r.get("standard", "")),
                    str(r.get("group", "")),
                    str(r.get("channel", "")),
                    str(r.get("bw_mhz", "")),
                    str(r.get("reason", "")),
                    str(r.get("test_key", "")),
                ]).lower()
                if search_text not in hay:
                    continue

            filtered.append(r)

        return filtered

    def _current_plan_id(self) -> str | None:
        return self._plan_controller.current_plan_id()

    def _find_plan_item(self, plan_id: str):
        return self._plan_controller.find_plan_item(plan_id)

    def _remove_plan_item_from_tree(self, plan_id: str) -> bool:
        return self._plan_controller.remove_plan_item_from_tree(plan_id)

    def on_remove_plan_from_scenario(self):
        self._plan_controller.remove_plan_from_scenario()

    def on_tree_clicked(self, index):
        self._plan_controller.tree_clicked(index)

    def _select_tree_node(self, item: QStandardItem):
        self._plan_controller.select_tree_node(item)

    def _load_page(self):
        self._plan_controller.load_page()

    def on_load_more(self):
        self._plan_controller.load_more()

    def on_skip_selected(self):
        self._plan_controller.skip_selected()

    def _on_run_progress(self, count: int, last_status: str, case_info=None):
        self._run_controller.handle_run_progress(count, last_status, case_info)
    def _on_scenario_run_progress(self, processed: int, total: int, preset_name: str, last_status: str):
        self._run_controller.handle_scenario_run_progress(processed, total, preset_name, last_status)
    def on_start_run(self):
        self._run_controller.start_run()
    def on_start_scenario_run(self):
        self._run_controller.start_scenario_run()
    def on_refresh_runs(self):
        if hasattr(self, "results_widget"):
            self.results_widget.refresh_runs()

    def on_load_results(self):
        if hasattr(self, "results_widget"):
            self.results_widget.load_results()

    def on_export_results_csv(self):
        if hasattr(self, "results_widget"):
            self.results_widget.export_results_csv()

    def on_export_results_excel(self):
        if hasattr(self, "results_widget"):
            self.results_widget.export_results_excel()

    def _update_result_quick_buttons_style(self):
        if hasattr(self, "results_widget") and hasattr(self.results_widget, "_update_result_quick_buttons_style"):
            self.results_widget._update_result_quick_buttons_style()

    def _on_run_finished(self, final_status: str, run_id: str, error_text: str):
        self._run_controller.handle_run_finished(final_status, run_id, error_text)
    def _on_scenario_run_finished(self, final_status: str, summaries: list, error_text: str):
        self._run_controller.handle_scenario_run_finished(final_status, summaries, error_text)
    def on_stop_run(self):
        self._run_controller.stop_run()
    def on_edit_execution_order(self):
        self._plan_controller.edit_execution_order()

    def _current_switch_path(self) -> str | None:
        return self._plan_controller.current_switch_path()

    def on_edit_rf_path(self):
        self._plan_controller.edit_rf_path()

    def _current_power_settings(self) -> dict:
        return self._plan_controller.current_power_settings()

    def on_edit_power_settings(self):
        self._plan_controller.edit_power_settings()

    def _current_motion_settings(self) -> dict:
        return self._plan_controller.current_motion_settings()

    def on_edit_motion_settings(self):
        self._plan_controller.edit_motion_settings()

    def _build_plan_control_summary(self) -> str:
        return self._plan_controller.build_plan_control_summary()

    def _validate_current_plan_controls(self, plan_id: str | None = None) -> tuple[bool, str]:
        target_plan_id = plan_id or self._current_plan_node_id
        ctx = self._plans.get(target_plan_id) if target_plan_id else None
        result = self.preflight_service.validate_plan_context(
            plan_ctx=ctx,
            equipment_profile_name=self._current_equipment_profile_name(),
        )
        return result.ok, result.first_error()

    def on_show_plan_summary(self):
        self._plan_controller.show_plan_summary()

    def on_create_rerun(self):
        if not self._last_run_id:
            QMessageBox.information(self, "No run", "Run first to generate FAIL-based re-run.")
            return
        if not self._current_plan_node_id:
            return
        ctx = self._plans[self._current_plan_node_id]

        try:
            new_preset_id = self.svc.create_rerun_preset_from_fail(
                project_id=ctx.project_id,
                base_preset_id=ctx.preset_id,
                run_id=self._last_run_id
            )
            QMessageBox.information(self, "Re-run preset created", f"New preset created.\nPreset ID: {new_preset_id}")
            # preset 콤보 갱신
            self._reload_presets(ctx.project_id, select_preset_id=new_preset_id)
        except Exception as e:
            QMessageBox.warning(self, "Re-run failed", str(e))
    
       
    def _scenario_plan_ids_in_tree_order(self) -> list[str]:
        return self._scenario_controller.scenario_plan_ids_in_tree_order()
    def _clear_scenario_internal(self):
        self._scenario_controller.clear_scenario_internal()
    def on_save_scenario(self):
        self._scenario_controller.save_scenario()
    def on_load_scenario(self):
        self._scenario_controller.load_scenario()
    def on_clear_scenario(self):
        self._scenario_controller.clear_scenario()
    def _legacy_on_results_show_all(self):
        self.result_filter_status.setCurrentText("ALL")
        self._update_result_quick_buttons_style()
        self.on_load_results()

    def _legacy_on_results_fail_only(self):
        self.result_filter_status.setCurrentText("FAIL")
        self._update_result_quick_buttons_style()
        self.on_load_results()

    def _legacy_on_results_error_only(self):
        self.result_filter_status.setCurrentText("ERROR")
        self._update_result_quick_buttons_style()
        self.on_load_results()
                    


    def on_apply_plan_filter(self):
        self._plan_controller.apply_filter()

    def on_clear_plan_filter(self):
        self._plan_controller.clear_filter()

    def on_group_drilldown(self, *args):
        self._plan_controller.drill_down_selected_group()

    def on_run_filtered(self):
        self._plan_controller.run_filtered()