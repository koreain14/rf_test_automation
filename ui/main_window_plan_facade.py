from __future__ import annotations

from typing import List

from PySide6.QtGui import QStandardItem

from ui.plan_context import PlanContext


class MainWindowPlanFacade:
    """Plan-related compatibility facade for MainWindow.

    MainWindow keeps its public API while delegating plan orchestration entry
    points through this helper. The actual plan logic remains in PlanController.
    """

    def __init__(self, window):
        self.window = window

    def on_reload_plan(self) -> None:
        self.window._plan_controller.reload_plan()

    def on_add_plan(self) -> None:
        self.window._plan_controller.add_plan()

    def effective_test_order(self, ctx: PlanContext) -> list[str]:
        return self.window._plan_controller.effective_test_order(ctx)

    def append_plan_to_tree(self, plan_id: str, ctx: PlanContext) -> QStandardItem:
        return self.window._plan_controller.append_plan_to_tree(plan_id, ctx)

    def refresh_plan_tree_order_only(self, plan_id: str, selected_test_type: str | None = None) -> bool:
        return self.window._plan_controller.refresh_plan_tree_order_only(plan_id, selected_test_type)

    def clear_cases_view(self) -> None:
        self.window._plan_controller.clear_cases_view()

    def current_plan_id(self) -> str | None:
        return self.window._plan_controller.current_plan_id()

    def find_plan_item(self, plan_id: str):
        return self.window._plan_controller.find_plan_item(plan_id)

    def remove_plan_item_from_tree(self, plan_id: str) -> bool:
        return self.window._plan_controller.remove_plan_item_from_tree(plan_id)

    def on_remove_plan_from_scenario(self) -> None:
        self.window._plan_controller.remove_plan_from_scenario()

    def on_tree_clicked(self, index) -> None:
        self.window._plan_controller.tree_clicked(index)

    def select_tree_node(self, item: QStandardItem) -> None:
        self.window._plan_controller.select_tree_node(item)

    def load_page(self) -> None:
        self.window._plan_controller.load_page()

    def on_load_more(self) -> None:
        self.window._plan_controller.load_more()

    def on_skip_selected(self) -> None:
        self.window._plan_controller.skip_selected()

    def on_edit_execution_order(self) -> None:
        self.window._plan_controller.edit_execution_order()

    def current_switch_path(self) -> str | None:
        return self.window._plan_controller.current_switch_path()

    def on_edit_rf_path(self) -> None:
        self.window._plan_controller.edit_rf_path()

    def current_power_settings(self) -> dict:
        return self.window._plan_controller.current_power_settings()

    def on_edit_power_settings(self) -> None:
        self.window._plan_controller.edit_power_settings()

    def current_motion_settings(self) -> dict:
        return self.window._plan_controller.current_motion_settings()

    def current_dut_control_mode(self) -> str:
        return self.window._plan_controller.current_dut_control_mode()

    def on_edit_motion_settings(self) -> None:
        self.window._plan_controller.edit_motion_settings()

    def on_edit_dut_control_mode(self) -> None:
        self.window._plan_controller.edit_dut_control_mode()

    def current_correction_settings(self) -> dict:
        return self.window._plan_controller.current_correction_settings()

    def on_edit_correction_settings(self) -> None:
        self.window._plan_controller.edit_correction_settings()

    def build_plan_control_summary(self) -> str:
        return self.window._plan_controller.build_plan_control_summary()

    def on_show_plan_summary(self) -> None:
        self.window._plan_controller.show_plan_summary()

    def on_apply_plan_filter(self) -> None:
        self.window._plan_controller.apply_filter()

    def on_clear_plan_filter(self) -> None:
        self.window._plan_controller.clear_filter()

    def on_group_drilldown(self, *args) -> None:
        self.window._plan_controller.drill_down_selected_group()

    def on_run_filtered(self) -> List[str]:
        return self.window._plan_controller.run_filtered()
