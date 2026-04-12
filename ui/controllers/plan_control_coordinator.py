from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox

from ui.correction_settings_dialog import CorrectionSettingsDialog
from ui.execution_order_dialog import ExecutionOrderDialog
from ui.motion_settings_dialog import MotionSettingsDialog
from ui.power_settings_dialog import PowerSettingsDialog
from ui.rf_path_dialog import RFPathDialog


class PlanControlCoordinator:
    def __init__(self, controller):
        self.controller = controller

    @property
    def window(self):
        return self.controller.window

    @property
    def control_service(self):
        return self.controller._control_service

    def edit_execution_order(self) -> None:
        ctx = self.controller._current_context()
        if not ctx:
            return
        current = self.controller.effective_test_order(ctx)
        dlg = ExecutionOrderDialog(initial_order=current, parent=self.window)
        if dlg.exec():
            order = dlg.get_order()
            try:
                self.window.svc.save_execution_order(ctx.preset_id, order)
                ruleset, preset, recipe, overrides = self.window.svc.build_recipe_from_preset(ctx.preset_id)
                ctx.ruleset = ruleset  # type: ignore[misc]
                ctx.preset = preset  # type: ignore[misc]
                ctx.recipe = recipe  # type: ignore[misc]
                ctx.overrides = overrides  # type: ignore[misc]
            except Exception as e:
                QMessageBox.warning(self.window, "Save failed", str(e))
                return
            self.controller.refresh_plan_tree_order_only(self.controller.current_plan_id())

    def current_switch_path(self) -> str | None:
        ctx = self.controller._current_context()
        return self.control_service.current_switch_path(ctx.recipe) if ctx else None

    def current_antenna(self) -> str | None:
        ctx = self.controller._current_context()
        return self.control_service.current_antenna(ctx.recipe) if ctx else None

    def edit_rf_path(self) -> None:
        ctx = self.controller._current_context()
        if not ctx:
            return
        profile_name = None
        if hasattr(self.window, "_current_equipment_profile_name"):
            try:
                profile_name = self.window._current_equipment_profile_name()
            except Exception:
                profile_name = None
        try:
            im = self.window.run_service.instrument_manager
            path_names = list(im.get_switch_path_names(profile_name))
            antenna_names = list(im.get_switch_port_names(profile_name))
        except Exception:
            path_names = []
            antenna_names = []
        dlg = RFPathDialog(
            path_names,
            antenna_names=antenna_names,
            current_path=self.current_switch_path(),
            current_antenna=self.current_antenna(),
            parent=self.window,
        )
        if dlg.exec():
            ctx.recipe = self.control_service.update_rf_path(ctx.recipe, dlg.selected_path(), dlg.selected_antenna())  # type: ignore[misc]

    def current_power_settings(self) -> dict:
        ctx = self.controller._current_context()
        return self.control_service.current_power(ctx.recipe) if ctx else {}

    def edit_power_settings(self) -> None:
        ctx = self.controller._current_context()
        if not ctx:
            return
        dlg = PowerSettingsDialog(initial=self.current_power_settings(), parent=self.window)
        if dlg.exec():
            ctx.recipe = self.control_service.update_power(ctx.recipe, dlg.settings())  # type: ignore[misc]

    def current_dut_control_mode(self) -> str:
        ctx = self.controller._current_context()
        return self.control_service.current_dut_control_mode(ctx.recipe) if ctx else "manual"

    def edit_dut_control_mode(self) -> None:
        ctx = self.controller._current_context()
        if not ctx:
            return
        items = ["manual", "auto_license", "auto_callbox"]
        current = self.current_dut_control_mode()
        try:
            current_index = items.index(current)
        except ValueError:
            current_index = 0
        value, ok = QInputDialog.getItem(
            self.window,
            "DUT Control Mode",
            "Select DUT control mode:",
            items,
            current_index,
            False,
        )
        if not ok:
            return
        ctx.recipe = self.control_service.update_dut_control_mode(ctx.recipe, value)  # type: ignore[misc]

    def current_motion_settings(self) -> dict:
        ctx = self.controller._current_context()
        return self.control_service.current_motion(ctx.recipe) if ctx else {}

    def current_correction_settings(self) -> dict:
        ctx = self.controller._current_context()
        return self.control_service.current_correction(ctx.recipe) if ctx else {}

    def edit_motion_settings(self) -> None:
        ctx = self.controller._current_context()
        if not ctx:
            return
        dlg = MotionSettingsDialog(initial=self.current_motion_settings(), parent=self.window)
        if dlg.exec():
            ctx.recipe = self.control_service.update_motion(ctx.recipe, dlg.settings())  # type: ignore[misc]

    def edit_correction_settings(self) -> None:
        ctx = self.controller._current_context()
        if not ctx:
            return
        bound_path = self.current_antenna() or self.current_switch_path() or ""
        dlg = CorrectionSettingsDialog(
            initial=self.current_correction_settings(),
            current_bound_path=bound_path,
            parent=self.window,
        )
        if dlg.exec():
            ctx.recipe = self.control_service.update_correction(ctx.recipe, dlg.settings())  # type: ignore[misc]

    def build_plan_control_summary(self) -> str:
        ctx = self.controller._current_context()
        if not ctx:
            return "No plan selected."
        return self.control_service.build_summary(ctx.preset.name, ctx.recipe, self.controller.effective_test_order(ctx))

    def show_plan_summary(self) -> None:
        QMessageBox.information(self.window, "Plan Summary", self.build_plan_control_summary())
