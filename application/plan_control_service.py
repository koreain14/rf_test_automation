from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

from application.plan_control_meta import get_antenna, get_correction, get_dut_control_mode, get_motion, get_power, get_switch_path
from application.run_display_formatter import build_plan_summary_lines


class PlanControlService:
    """Plan control metadata helper.

    Keeps recipe.meta access and updates consistent so controllers do not manipulate
    raw dicts directly.
    """

    def get_meta(self, recipe: Any) -> Dict[str, Any]:
        return dict((getattr(recipe, "meta", {}) or {}))

    def replace_meta(self, recipe: Any, meta: Dict[str, Any]):
        return replace(recipe, meta=dict(meta or {}))

    def update_meta(self, recipe: Any, updates: Dict[str, Any]):
        meta = self.get_meta(recipe)
        meta.update(updates)
        return self.replace_meta(recipe, meta)

    def current_switch_path(self, recipe: Any) -> str | None:
        value = get_switch_path(self.get_meta(recipe))
        return value or None

    def current_antenna(self, recipe: Any) -> str | None:
        value = get_antenna(self.get_meta(recipe))
        return value or None

    def current_power(self, recipe: Any) -> dict:
        return get_power(self.get_meta(recipe))

    def current_motion(self, recipe: Any) -> dict:
        return get_motion(self.get_meta(recipe))

    def current_correction(self, recipe: Any) -> dict:
        return get_correction(self.get_meta(recipe))

    def current_dut_control_mode(self, recipe: Any) -> str:
        return get_dut_control_mode(self.get_meta(recipe))

    def update_dut_control_mode(self, recipe: Any, mode: str):
        value = str(mode or "manual").strip().lower()
        if value not in {"manual", "auto_license", "auto_callbox"}:
            value = "manual"
        return self.update_meta(recipe, {"dut_control_mode": value})

    def update_rf_path(self, recipe: Any, switch_path: str, antenna: str):
        meta = self.get_meta(recipe)
        rf = dict(meta.get("rf_path") or {})
        rf["switch_path"] = switch_path
        rf["antenna"] = antenna
        meta["rf_path"] = rf
        return self.replace_meta(recipe, meta)

    def update_power(self, recipe: Any, settings: dict):
        return self.update_meta(recipe, {"power_control": dict(settings or {})})

    def update_motion(self, recipe: Any, settings: dict):
        return self.update_meta(recipe, {"motion_control": dict(settings or {})})

    def update_correction(self, recipe: Any, settings: dict):
        return self.update_meta(recipe, {"correction": dict(settings or {})})

    def build_summary(self, preset_name: str, recipe: Any, execution_order: list[str]) -> str:
        return build_plan_summary_lines(preset_name, self.get_meta(recipe), execution_order)
