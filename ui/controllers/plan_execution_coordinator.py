from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtWidgets import QMessageBox

from application.plan_models import PlanFilter, PlanQuery


class PlanExecutionCoordinator:
    def __init__(self, controller):
        self.controller = controller

    @property
    def window(self):
        return self.controller.window

    @property
    def query_service(self):
        return self.controller._query_service

    def selected_case_keys(self) -> List[str]:
        view = self.window.table
        sel = view.selectionModel()
        if sel is None:
            return []
        rows = sorted({idx.row() for idx in sel.selectedRows()})
        keys: List[str] = []
        for row in rows:
            item = self.window.case_model.row_at(row)
            if item:
                keys.append(str(item.get("case_key") or item.get("id") or item.get("key")))
        return keys

    def runnable_case_keys(self, selected_only: bool = False) -> List[str]:
        if selected_only:
            return self.selected_case_keys()
        return self.execution_target_keys(scope="filtered")

    def current_execution_query(self, scope: str = "filtered") -> PlanQuery:
        normalized = str(scope or "filtered").strip().lower()
        if normalized == "all":
            return PlanQuery(
                filters=PlanFilter(),
                sort=tuple(self.controller._current_sort or ()),
                page=1,
                page_size=1,
                policy={},
            )
        return PlanQuery(
            filters=self.controller._effective_filter(),
            sort=tuple(self.controller._current_sort or ()),
            page=1,
            page_size=1,
            policy={},
        )

    def execution_target_keys(self, scope: str = "filtered") -> List[str]:
        ctx = self.controller._current_context()
        if not ctx:
            return []
        return self.execution_target_keys_for_plan(plan_id=self.controller.current_plan_id() or "", scope=scope)

    def execution_target_keys_for_plan(self, *, plan_id: str, scope: str = "all") -> List[str]:
        normalized = str(scope or "all").strip().lower()
        if normalized == "selected":
            current_plan_id = self.controller.current_plan_id()
            if current_plan_id == str(plan_id or ""):
                return self.selected_case_keys()
            return []

        ctx = self.window._plans.get(str(plan_id or ""))
        if not ctx:
            return []

        if normalized == "all":
            query = PlanQuery(
                filters=PlanFilter(),
                sort=tuple(self.controller._current_sort or ()),
                page=1,
                page_size=1,
                policy={},
            )
        else:
            if self.controller.current_plan_id() == str(plan_id or ""):
                query = self.current_execution_query(scope=normalized)
            else:
                query = PlanQuery(
                    filters=PlanFilter(),
                    sort=tuple(self.controller._current_sort or ()),
                    page=1,
                    page_size=1,
                    policy={},
                )

        return self.query_service.query_runnable_case_keys(ctx=ctx, query=query)

    def skip_selected(self) -> None:
        QMessageBox.information(
            self.window,
            "Filter-Driven Execution",
            "Row-level skip/enable is not used in this version. Use filters, group drill-down, and Run Filtered instead.",
        )

    def run_filtered(self) -> List[str]:
        keys = self.execution_target_keys(scope="filtered")
        if not keys:
            QMessageBox.information(self.window, "No runnable cases", "No enabled cases match the current filter.")
            return []
        self.window._run_controller.start_run_filtered()
        return keys
