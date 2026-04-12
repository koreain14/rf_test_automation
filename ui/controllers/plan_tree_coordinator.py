from __future__ import annotations

import uuid
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QMessageBox

from application.plan_models import PlanFilter, PlanQuery
from ui.plan_context import PlanContext


class PlanTreeCoordinator:
    def __init__(self, controller):
        self.controller = controller

    @property
    def window(self):
        return self.controller.window

    @property
    def query_service(self):
        return self.controller._query_service

    def add_plan(self) -> None:
        w = self.window
        if not w.project_id:
            QMessageBox.warning(w, "No project", "Select a project.")
            return
        if not w.preset_id:
            QMessageBox.warning(w, "No preset", "Select a preset first.")
            return
        try:
            ruleset, preset, recipe, overrides = w.svc.build_recipe_from_preset(w.preset_id)
        except Exception as e:
            QMessageBox.critical(w, "Build Plan Failed", str(e))
            return

        plan_id = f"PLAN::{uuid.uuid4().hex[:12]}"
        ctx = PlanContext(
            project_id=w.project_id,
            preset_id=w.preset_id,
            ruleset=ruleset,
            preset=preset,
            recipe=recipe,
            overrides=overrides,
            all_cases=[],
            case_enabled={},
            case_order=[],
            deleted_case_keys=set(),
        )
        w._plans[plan_id] = ctx
        item = self.append_plan_to_tree(plan_id, ctx)
        self.select_tree_node(item)
        self.controller.refresh_filter_options()
        total_cases = self.query_service.query_count(
            ctx=ctx,
            query=PlanQuery(filters=PlanFilter(), page=1, page_size=1),
        )
        w.statusBar().showMessage(f"Plan added: {preset.name} ({total_cases} cases)", 5000)

    def reload_plan(self) -> None:
        ctx = self.current_context()
        if not ctx:
            self.controller.clear_cases_view()
            return
        self.query_service.invalidate_context_cache(
            ctx=ctx,
            reset_case_order=True,
            clear_hydrated_cases=True,
        )
        self.controller._current_page = 1
        self.refresh_plan_tree_order_only(self.current_plan_id())
        self.controller.refresh_filter_options()
        self.controller.load_group_summary()
        self.controller.load_detail_page(page=1)

    def ensure_cases_loaded(self, ctx: Optional[PlanContext] = None, force: bool = False) -> None:
        ctx = ctx or self.current_context()
        if not ctx:
            return
        if ctx.all_cases and not force:
            return
        self.query_service._ensure_context_cases(ctx)

    def append_plan_to_tree(self, plan_id: str, ctx: PlanContext) -> QStandardItem:
        root = self.window.tree_model.invisibleRootItem()
        parent = QStandardItem(ctx.preset.name)
        parent.setEditable(False)
        parent.setData(plan_id, Qt.UserRole)
        parent.setData({"kind": "plan", "plan_id": plan_id}, Qt.UserRole + 1)
        counts = self.controller._test_counts_for_tree(ctx=ctx)
        effective_order = self.controller.effective_test_order(ctx)
        for test_type in effective_order:
            if test_type not in counts:
                continue
            child = QStandardItem(f"{test_type} ({counts[test_type]})")
            child.setEditable(False)
            child.setData(plan_id, Qt.UserRole)
            child.setData({"kind": "test", "plan_id": plan_id, "test_type": test_type}, Qt.UserRole + 1)
            parent.appendRow(child)
        for test_type, cnt in sorted(counts.items()):
            if test_type in effective_order:
                continue
            child = QStandardItem(f"{test_type} ({cnt})")
            child.setEditable(False)
            child.setData(plan_id, Qt.UserRole)
            child.setData({"kind": "test", "plan_id": plan_id, "test_type": test_type}, Qt.UserRole + 1)
            parent.appendRow(child)
        root.appendRow(parent)
        self.window.tree.expand(parent.index())
        return parent

    def refresh_plan_tree_order_only(self, plan_id: str, selected_test_type: str | None = None) -> bool:
        item = self.find_plan_item(plan_id)
        ctx = self.window._plans.get(plan_id)
        if item is None or ctx is None:
            return False
        while item.rowCount() > 0:
            item.removeRow(0)
        counts = self.controller._test_counts_for_tree(ctx=ctx)
        for test_type in self.controller.effective_test_order(ctx):
            if test_type not in counts:
                continue
            child = QStandardItem(f"{test_type} ({counts[test_type]})")
            child.setEditable(False)
            child.setData(plan_id, Qt.UserRole)
            child.setData({"kind": "test", "plan_id": plan_id, "test_type": test_type}, Qt.UserRole + 1)
            item.appendRow(child)
        return True

    def current_plan_id(self) -> str | None:
        return self.window._current_plan_node_id

    def find_plan_item(self, plan_id: str):
        root = self.window.tree_model.invisibleRootItem()
        for row in range(root.rowCount()):
            item = root.child(row)
            if item and item.data(Qt.UserRole) == plan_id:
                return item
        return None

    def remove_plan_item_from_tree(self, plan_id: str) -> bool:
        root = self.window.tree_model.invisibleRootItem()
        for row in range(root.rowCount()):
            item = root.child(row)
            if item and item.data(Qt.UserRole) == plan_id:
                root.removeRow(row)
                return True
        return False

    def remove_plan_from_scenario(self) -> None:
        plan_id = self.current_plan_id()
        if not plan_id:
            return
        self.window._plans.pop(plan_id, None)
        self.remove_plan_item_from_tree(plan_id)
        self.window._current_plan_node_id = None
        self.controller.clear_cases_view()

    def tree_clicked(self, index) -> None:
        item = self.window.tree_model.itemFromIndex(index)
        if item is not None:
            self.select_tree_node(item)

    def select_tree_node(self, item: QStandardItem) -> None:
        meta = item.data(Qt.UserRole + 1) or {}
        plan_id = meta.get("plan_id") or item.data(Qt.UserRole)
        self.window._current_plan_node_id = plan_id
        test_type = meta.get("test_type") if meta.get("kind") == "test" else None
        self.window._tree_filter = {"test_type": test_type} if test_type else None
        self.controller._current_page = 1
        self.controller.refresh_filter_options()
        self.controller.load_group_summary()
        self.controller.load_detail_page(page=1)
        self.window.tree.setCurrentIndex(item.index())

    def current_context(self) -> Optional[PlanContext]:
        plan_id = self.current_plan_id()
        return self.window._plans.get(plan_id) if plan_id else None
