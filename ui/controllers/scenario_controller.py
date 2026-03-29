from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ui.plan_context import PlanContext


class ScenarioController:
    """Owns scenario persistence and scenario tree lifecycle."""

    def __init__(self, window):
        self.window = window

    def scenario_plan_ids_in_tree_order(self) -> list[str]:
        w = self.window
        root = w.tree_model.invisibleRootItem()
        out: list[str] = []
        for row in range(root.rowCount()):
            it = root.child(row)
            if not it:
                continue
            plan_id = it.data(Qt.UserRole)
            if plan_id:
                out.append(str(plan_id))
        return out

    def clear_scenario_internal(self) -> None:
        w = self.window
        w._plans.clear()
        root = w.tree_model.invisibleRootItem()
        if root.rowCount() > 0:
            root.removeRows(0, root.rowCount())

        if hasattr(w, "_current_plan_node_id"):
            w._current_plan_node_id = None
        if hasattr(w, "_current_filter"):
            w._current_filter = None
        if hasattr(w, "_current_offset"):
            w._current_offset = 0
        if hasattr(w, "case_model"):
            try:
                w.case_model.clear()
            except Exception:
                pass

    def save_scenario(self) -> None:
        w = self.window
        if not w.project_id:
            QMessageBox.warning(w, "No project", "Select a project.")
            return

        plan_ids = self.scenario_plan_ids_in_tree_order()
        plans = []
        for pid in plan_ids:
            ctx = w._plans.get(pid)
            if not ctx:
                continue
            plans.append({
                "plan_id": pid,
                "preset_id": ctx.preset_id,
                "case_enabled": dict(ctx.case_enabled or {}),
                "case_order": list(ctx.case_order or []),
                "deleted_case_keys": sorted(ctx.deleted_case_keys or []),
                "recipe_meta": dict((ctx.recipe.meta or {}) if getattr(ctx, "recipe", None) else {}),
            })

        data = {
            "version": "1.0",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "project_id": w.project_id,
            "plans": plans,
        }

        path, _ = QFileDialog.getSaveFileName(w, "Save Scenario", "scenario.json", "Scenario (*.json)")
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(w, "Save failed", str(e))
            return

        QMessageBox.information(w, "Saved", f"Scenario saved:\n{path}")

    def load_scenario(self) -> None:
        w = self.window
        path, _ = QFileDialog.getOpenFileName(w, "Load Scenario", "", "Scenario (*.json)")
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(w, "Load failed", str(e))
            return

        file_project_id = data.get("project_id")
        plans = data.get("plans", [])

        if not w.project_id:
            QMessageBox.warning(w, "No project", "Select a project before loading.")
            return

        if file_project_id and file_project_id != w.project_id:
            ret = QMessageBox.question(
                w,
                "Project mismatch",
                f"Scenario project_id differs.\n\n"
                f"File: {file_project_id}\nCurrent: {w.project_id}\n\n"
                f"Load anyway?",
                QMessageBox.Yes | QMessageBox.No
            )
            if ret != QMessageBox.Yes:
                return

        self.clear_scenario_internal()

        failures: list[str] = []
        for p in plans:
            preset_id = p.get("preset_id")
            if not preset_id:
                continue

            try:
                ruleset, preset, recipe, overrides = w.svc.build_recipe_from_preset(preset_id)
            except Exception as e:
                failures.append(f"{preset_id}: {e}")
                continue

            plan_id = p.get("plan_id") or f"PLAN::{uuid.uuid4()}"

            recipe_meta = dict(p.get("recipe_meta") or {})
            if recipe_meta:
                recipe = replace(recipe, meta=dict(recipe_meta))

            ctx = PlanContext(
                project_id=w.project_id,
                preset_id=preset_id,
                ruleset=ruleset,
                preset=preset,
                recipe=recipe,
                overrides=overrides,
                case_enabled=dict(p.get("case_enabled") or {}),
                case_order=list(p.get("case_order") or []),
                deleted_case_keys=set(p.get("deleted_case_keys") or []),
            )
            w._plans[str(plan_id)] = ctx
            w._append_plan_to_tree(str(plan_id), ctx)

        root = w.tree_model.invisibleRootItem()
        if root.rowCount() > 0:
            first = root.child(0)
            if first:
                w.tree.expand(first.index())
                w.tree.setCurrentIndex(first.index())
                w._select_tree_node(first)

        if failures:
            QMessageBox.warning(w, "Loaded with warnings", "Some plans failed to load:\n\n" + "\n".join(failures[:30]))
        else:
            QMessageBox.information(w, "Loaded", "Scenario loaded.")

    def clear_scenario(self) -> None:
        w = self.window
        if not w._plans:
            return

        ret = QMessageBox.question(
            w,
            "Clear Scenario",
            "Remove all plans from the scenario?\n(This does NOT delete presets/runs.)",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return

        self.clear_scenario_internal()
