from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtWidgets import QMessageBox

from application.plan_control_meta import (
    build_run_display_context,
    build_status_suffix,
    get_antenna,
    get_motion,
)


class MainWindowRuntimeHelper:
    def __init__(self, window):
        self.window = window

    def runtime_instrument_manager(self):
        manager = getattr(self.window.run_service, "instrument_manager", None)
        if manager is None:
            raise TypeError(
                f"Configured run_service '{type(self.window.run_service).__name__}' does not expose instrument_manager."
            )
        return manager

    def validate_runtime_services(self) -> None:
        if not hasattr(self.window.run_service, "run"):
            raise TypeError(
                f"Configured run_service '{type(self.window.run_service).__name__}' does not expose run()."
            )
        manager = self.runtime_instrument_manager()
        missing = [name for name in ("set_factory", "get_switch_path_names", "get_switch_port_names") if not hasattr(manager, name)]
        if missing:
            raise TypeError(
                f"Configured instrument_manager '{type(manager).__name__}' is missing required methods: {', '.join(missing)}"
            )

    def attach_runtime_dependencies(self) -> None:
        manager = self.runtime_instrument_manager()
        manager.device_registry = self.window.device_registry
        manager.profile_repo = self.window.profile_repo
        manager.discovery = self.window.device_discovery

    def reset_run_selection_state(self) -> None:
        w = self.window
        w._worker = None
        w._scenario_worker = None
        w._last_run_id = None
        w._last_results_rows = []
        w._scenario_total_cases = 0
        w._scenario_processed_cases = 0
        w._scenario_run_summaries = []
        w._run_total_cases = 0
        w._run_processed_cases = 0
        w._run_pass_count = 0
        w._run_fail_count = 0
        w._run_skip_count = 0
        w._run_error_count = 0
        w._running_preset_name = ""
        w._running_equipment_profile_name = ""
        w.lbl_status.setText("Idle")
        w.progress_run.setMaximum(100)
        w.progress_run.setValue(0)
        w.progress_run.setFormat("Idle")

    def reset_project_runtime_state(self) -> None:
        w = self.window
        w._scenario_controller.clear_scenario_internal()
        w._plans.clear()
        w._current_plan_node_id = None
        w._tree_filter = None
        w._plan_filter_bar = None
        w._current_group_filter = None
        w._current_filter = None
        w._current_offset = 0
        self.reset_run_selection_state()
        if hasattr(w, "results_widget"):
            w.results_widget.reset_view()
        if hasattr(w, "compare_widget"):
            w.compare_widget.reset_view()
            if w.project_id:
                w.compare_widget.refresh_runs()


class MainWindowDisplayHelper:
    def __init__(self, window):
        self.window = window

    def current_antenna(self) -> str | None:
        if hasattr(self.window, "_plan_controller") and self.window._plan_controller is not None:
            return self.window._plan_controller.current_antenna()
        return None

    def current_plan_meta(self) -> dict:
        if hasattr(self.window, "_plan_controller") and self.window._plan_controller is not None:
            try:
                ctx = self.window._plan_controller._current_context()
                if ctx and getattr(ctx, "recipe", None):
                    return dict(ctx.recipe.meta or {})
            except Exception:
                pass
        return {}

    def run_display_context(self) -> dict:
        return build_run_display_context(self.current_plan_meta())

    def antenna_display_suffix(self) -> str:
        return build_status_suffix({"rf_path": {"antenna": get_antenna(self.current_plan_meta())}})

    def motion_display_suffix(self) -> str:
        return (" | " + self.run_display_context().get("motion_text")) if self.run_display_context().get("motion_text") else ""

    def power_display_suffix(self) -> str:
        return (" | " + self.run_display_context().get("power_text")) if self.run_display_context().get("power_text") else ""

    def equipment_display_suffix(self) -> str:
        profile_name = self.window._current_equipment_profile_name()
        if not profile_name:
            return ""
        profile = self.window.profile_repo.get_profile(profile_name)
        parts = [f"EQ:{profile_name}"]
        analyzer = getattr(profile, "analyzer", None) if profile else None
        if analyzer:
            parts.append(f"AN:{analyzer}")
        return " | " + " | ".join(parts)

    def equipment_status_suffix(self) -> str:
        profile_name = self.window._current_equipment_profile_name()
        return f" | EQ:{profile_name}" if profile_name else ""


class MainWindowProjectHelper:
    def __init__(self, window):
        self.window = window

    def reload_equipment_profiles(self, select_profile_name: Optional[str] = None):
        combo = self.window.profile_combo
        combo.blockSignals(True)
        current = select_profile_name or combo.currentData()
        combo.clear()

        profiles = self.window.profile_repo.list_profiles()
        combo.addItem("(None)", None)
        for profile in profiles:
            combo.addItem(profile.name, profile.name)

        if current:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def load_initial_data(self):
        project_id = self.window.svc.ensure_default_project()
        self.reload_projects(select_project_id=project_id)
        self.reload_presets(project_id)

        if self.window.project_combo.count() > 0 and self.window.project_combo.currentIndex() < 0:
            self.window.project_combo.setCurrentIndex(0)
        if self.window.preset_combo.count() > 0 and self.window.preset_combo.currentIndex() < 0:
            self.window.preset_combo.setCurrentIndex(0)

        self.window.project_id = self.window.project_combo.currentData()
        self.window.preset_id = self.window.preset_combo.currentData()

        self.reload_equipment_profiles()
        if self.window.project_id:
            self.window.on_project_changed(self.window.project_combo.currentIndex())
        else:
            self.window.project_id = None
            self.window.preset_id = None

        if self.window.preset_id:
            self.window.on_preset_changed(self.window.preset_combo.currentIndex())

    def reload_projects(self, select_project_id: Optional[str] = None):
        combo = self.window.project_combo
        combo.blockSignals(True)
        combo.clear()

        projects = self.window.svc.list_projects()
        for project in projects:
            combo.addItem(project["name"], userData=project["project_id"])

        combo.blockSignals(False)

        if select_project_id:
            idx = combo.findData(select_project_id)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def reload_presets(self, project_id: str, select_preset_id: Optional[str] = None):
        combo = self.window.preset_combo
        previous_preset_id = combo.currentData()

        combo.blockSignals(True)
        combo.clear()

        presets = self.window.svc.list_presets(project_id)
        for preset in presets:
            combo.addItem(preset["name"], userData=preset["preset_id"])

        combo.blockSignals(False)

        target_id = select_preset_id or previous_preset_id
        idx = combo.findData(target_id) if target_id else -1
        if idx < 0 and combo.count() > 0:
            idx = 0
        if idx >= 0:
            combo.setCurrentIndex(idx)
            self.window.preset_id = combo.currentData()
        else:
            self.window.preset_id = None

    def handle_project_changed(self, _idx: int):
        w = self.window
        previous_project_id = w.project_id
        pid = w.project_combo.currentData()
        if (
            previous_project_id
            and pid != previous_project_id
            and (
                (getattr(w, "_worker", None) and w._worker.isRunning())
                or (getattr(w, "_scenario_worker", None) and w._scenario_worker.isRunning())
            )
        ):
            QMessageBox.warning(w, "Project change blocked", "Stop the current run before switching projects.")
            w.project_combo.blockSignals(True)
            idx = w.project_combo.findData(previous_project_id)
            if idx >= 0:
                w.project_combo.setCurrentIndex(idx)
            w.project_combo.blockSignals(False)
            return
        w.project_id = str(pid) if pid else None

        if w.project_id:
            self.reload_presets(w.project_id)
        else:
            w.preset_combo.blockSignals(True)
            w.preset_combo.clear()
            w.preset_combo.blockSignals(False)
            w.preset_id = None

        w.preset_id = w.preset_combo.currentData()
        w._reset_project_runtime_state()

    def handle_preset_changed(self, _idx: int):
        self.window.preset_id = self.window.preset_combo.currentData()

    def open_preset_editor(self):
        from ui.dialogs import PresetEditorDialog

        dlg = PresetEditorDialog(
            preset_repo=self.window.preset_file_repo,
            plan_repo=getattr(self.window.svc, "repo", None),
            project_id=self.window.project_id,
            parent=self.window,
        )
        before = {p["preset_id"]: p["name"] for p in (self.window.svc.list_presets(self.window.project_id) if self.window.project_id else [])}
        dlg.exec()
        if self.window.project_id:
            selected_preset_id = getattr(dlg, "last_imported_project_preset_id", None)
            self.reload_presets(self.window.project_id, select_preset_id=selected_preset_id)
            after = {p["preset_id"]: p["name"] for p in self.window.svc.list_presets(self.window.project_id)}
            if len(after) != len(before):
                new_names = sorted(set(after.values()) - set(before.values()))
                if new_names:
                    self.window.statusBar().showMessage(f"Imported presets: {', '.join(new_names)}", 5000)

    def open_ruleset_axis_editor(self) -> None:
        from ui.dialogs import RulesetAxisEditorDialog

        ruleset_id = self._resolve_current_ruleset_id()
        raw = self._load_ruleset_json(ruleset_id)
        if not raw:
            QMessageBox.warning(
                self.window,
                "Ruleset Axis Editor",
                f"Could not load ruleset JSON for '{ruleset_id}'.",
            )
            return
        dlg = RulesetAxisEditorDialog(ruleset_data=raw, parent=self.window)
        dlg.exec()

    def _resolve_current_ruleset_id(self) -> str:
        preset_id = getattr(self.window, "preset_id", None)
        if preset_id:
            try:
                preset = self.window.svc.load_preset_obj(preset_id)
                if getattr(preset, "ruleset_id", ""):
                    return str(preset.ruleset_id)
            except Exception:
                pass
        return "KC_WLAN"

    def _load_ruleset_json(self, ruleset_id: str) -> dict:
        normalized = str(ruleset_id or "").strip()
        if not normalized:
            return {}
        path = Path(getattr(self.window.svc, "ruleset_dir", Path("rulesets"))) / f"{normalized.lower()}.json"
        if not path.exists() and normalized.upper() == "KC_WLAN":
            alt = Path(getattr(self.window.svc, "ruleset_dir", Path("rulesets"))) / "kc_wlan.json"
            if alt.exists():
                path = alt
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
