from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from application.plan_control_service import PlanControlService
from application.plan_models import PlanFilter, PlanQuery, PlanSortSpec
from application.plan_query_service import PlanQueryService
from application.test_type_symbols import DEFAULT_TEST_ORDER, normalize_test_type_list
from ui.controllers.plan_control_coordinator import PlanControlCoordinator
from ui.controllers.plan_execution_coordinator import PlanExecutionCoordinator
from ui.controllers.plan_filter_paging_coordinator import PlanFilterPagingCoordinator
from ui.controllers.plan_tree_coordinator import PlanTreeCoordinator
from ui.plan_context import PlanContext

log = logging.getLogger(__name__)


class PlanController:
    def __init__(self, window):
        self.window = window
        self._current_filter = PlanFilter()
        self._group_drill_filter: Optional[PlanFilter] = None
        self._current_page = 1
        self._page_size = 200
        self._visible_rows: List[Dict[str, Any]] = []
        self._current_sort: tuple[PlanSortSpec, ...] = tuple()
        self._query_service = PlanQueryService(window.svc)
        self._control_service = PlanControlService()

        self._tree = PlanTreeCoordinator(self)
        self._filter_paging = PlanFilterPagingCoordinator(self)
        self._execution = PlanExecutionCoordinator(self)
        self._control = PlanControlCoordinator(self)

        self._ui_bound = False
        self.bind_ui()

    def bind_ui(self) -> None:
        if self._ui_bound:
            return
        pw = getattr(self.window, "plan_widget", None)
        if pw is None:
            return
        pw.btn_prev_page.clicked.connect(self.prev_page)
        pw.btn_next_page.clicked.connect(self.next_page)
        pw.page_size_combo.currentTextChanged.connect(self.set_page_size)
        pw.plan_filter_band.currentTextChanged.connect(self._on_filter_band_changed)
        try:
            pw.page_size_combo.currentIndexChanged.connect(lambda *_: self.set_page_size(pw.page_size_combo.currentText()))
        except Exception:
            pass
        self._ui_bound = True
        log.info("PlanController UI bound | page_size=%s", getattr(self, "_page_size", None))

    # ---------- Plan lifecycle ----------
    def add_plan(self) -> None:
        self._tree.add_plan()

    def reload_plan(self) -> None:
        self._tree.reload_plan()

    def _ensure_cases_loaded(self, ctx: Optional[PlanContext] = None, force: bool = False) -> None:
        self._tree.ensure_cases_loaded(ctx=ctx, force=force)

    # ---------- Tree ----------
    def effective_test_order(self, ctx: PlanContext) -> list[str]:
        order = normalize_test_type_list((((ctx.recipe.meta or {}).get("execution_policy") or {}).get("test_order") or []))
        if order:
            return list(order)
        return list(DEFAULT_TEST_ORDER)

    def append_plan_to_tree(self, plan_id: str, ctx: PlanContext):
        return self._tree.append_plan_to_tree(plan_id, ctx)

    def refresh_plan_tree_order_only(self, plan_id: str, selected_test_type: str | None = None) -> bool:
        return self._tree.refresh_plan_tree_order_only(plan_id, selected_test_type)

    def current_plan_id(self) -> str | None:
        return self._tree.current_plan_id()

    def find_plan_item(self, plan_id: str):
        return self._tree.find_plan_item(plan_id)

    def remove_plan_item_from_tree(self, plan_id: str) -> bool:
        return self._tree.remove_plan_item_from_tree(plan_id)

    def remove_plan_from_scenario(self) -> None:
        self._tree.remove_plan_from_scenario()

    def tree_clicked(self, index) -> None:
        self._tree.tree_clicked(index)

    def select_tree_node(self, item) -> None:
        self._tree.select_tree_node(item)

    # ---------- Filtering / paging ----------
    def apply_filter(self) -> None:
        self._filter_paging.apply_filter()

    def clear_filter(self) -> None:
        self._filter_paging.clear_filter()

    def load_group_summary(self) -> None:
        self._filter_paging.load_group_summary()

    def drill_down_selected_group(self) -> None:
        self._filter_paging.drill_down_selected_group()

    def load_page(self) -> None:
        self._filter_paging.load_page()

    def load_more(self) -> None:
        self._filter_paging.load_more()

    def load_detail_page(self, page: Optional[int] = None, append: bool = False) -> None:
        self._filter_paging.load_detail_page(page=page, append=append)

    def next_page(self) -> None:
        self._filter_paging.next_page()

    def prev_page(self) -> None:
        self._filter_paging.prev_page()

    def set_page_size(self, value: Any) -> None:
        self._filter_paging.set_page_size(value)

    def clear_cases_view(self) -> None:
        self._filter_paging.clear_cases_view()

    # ---------- Selection / run ----------
    def selected_case_keys(self) -> List[str]:
        return self._execution.selected_case_keys()

    def runnable_case_keys(self, selected_only: bool = False) -> List[str]:
        return self._execution.runnable_case_keys(selected_only=selected_only)

    def current_execution_query(self, scope: str = "filtered") -> PlanQuery:
        return self._execution.current_execution_query(scope=scope)

    def execution_target_keys(self, scope: str = "filtered") -> List[str]:
        return self._execution.execution_target_keys(scope=scope)

    def execution_target_keys_for_plan(self, *, plan_id: str, scope: str = "all") -> List[str]:
        return self._execution.execution_target_keys_for_plan(plan_id=plan_id, scope=scope)

    def skip_selected(self) -> None:
        self._execution.skip_selected()

    def run_filtered(self) -> List[str]:
        return self._execution.run_filtered()

    # ---------- Plan control dialogs ----------
    def edit_execution_order(self) -> None:
        self._control.edit_execution_order()

    def current_switch_path(self) -> str | None:
        return self._control.current_switch_path()

    def current_antenna(self) -> str | None:
        return self._control.current_antenna()

    def edit_rf_path(self) -> None:
        self._control.edit_rf_path()

    def current_power_settings(self) -> dict:
        return self._control.current_power_settings()

    def edit_power_settings(self) -> None:
        self._control.edit_power_settings()

    def current_dut_control_mode(self) -> str:
        return self._control.current_dut_control_mode()

    def edit_dut_control_mode(self) -> None:
        self._control.edit_dut_control_mode()

    def current_correction_settings(self) -> dict:
        return self._control.current_correction_settings()

    def edit_correction_settings(self) -> None:
        self._control.edit_correction_settings()

    def current_motion_settings(self) -> dict:
        return self._control.current_motion_settings()

    def edit_motion_settings(self) -> None:
        self._control.edit_motion_settings()

    def build_plan_control_summary(self) -> str:
        return self._control.build_plan_control_summary()

    def show_plan_summary(self) -> None:
        self._control.show_plan_summary()

    # ---------- Internal ----------
    def _current_context(self) -> Optional[PlanContext]:
        return self._tree.current_context()

    def _read_filter_from_ui(self) -> PlanFilter:
        return self._filter_paging.read_filter_from_ui()

    def _clear_filter_ui(self) -> None:
        self._filter_paging.clear_filter_ui()

    def refresh_filter_options(self) -> None:
        self._filter_paging.refresh_filter_options()

    def _set_combo_values(self, combo, values: List[str], current: str) -> None:
        self._filter_paging.set_combo_values(combo, values, current)

    def _available_bands_for_context(self, ctx: Optional[PlanContext]) -> List[str]:
        return self._filter_paging.available_bands_for_context(ctx)

    def _available_standards_for_context(self, ctx: Optional[PlanContext], *, selected_band: str = "") -> List[str]:
        return self._filter_paging.available_standards_for_context(ctx, selected_band=selected_band)

    def _available_bandwidths_for_context(self, ctx: Optional[PlanContext]) -> List[int]:
        return self._filter_paging.available_bandwidths_for_context(ctx)

    def _on_filter_band_changed(self, _value: str) -> None:
        self._filter_paging.on_filter_band_changed(_value)

    def _build_query(self, *, page: Optional[int] = None, page_size: Optional[int] = None) -> PlanQuery:
        resolved_page = self._current_page if page is None else max(1, int(page))
        try:
            resolved_page_size = self._page_size if page_size is None else int(page_size)
        except Exception:
            resolved_page_size = self._page_size
        resolved_page_size = max(1, min(int(resolved_page_size or 200), 5000))
        return PlanQuery(
            filters=self._effective_filter(),
            sort=tuple(self._current_sort or ()),
            page=resolved_page,
            page_size=resolved_page_size,
            policy={},
        )

    def _test_counts_for_tree(self, *, ctx: PlanContext) -> Dict[str, int]:
        return self._query_service.context_test_counts(ctx=ctx, plan_filter=PlanFilter())

    def _effective_filter(self) -> PlanFilter:
        base = self._current_filter
        if self.window._tree_filter and self.window._tree_filter.get("test_type"):
            base = PlanFilter(
                band=base.band,
                standard=base.standard,
                phy_mode=base.phy_mode,
                bandwidth_mhz=base.bandwidth_mhz,
                channel_from=base.channel_from,
                channel_to=base.channel_to,
                test_type=self.window._tree_filter["test_type"],
                enabled_state=base.enabled_state,
                search_text=base.search_text,
            )
        if not self._group_drill_filter:
            return base
        gd = self._group_drill_filter
        return PlanFilter(
            band=gd.band or base.band,
            standard=gd.standard or base.standard,
            phy_mode=base.phy_mode,
            bandwidth_mhz=gd.bandwidth_mhz if gd.bandwidth_mhz not in (None, "") else base.bandwidth_mhz,
            channel_from=base.channel_from,
            channel_to=base.channel_to,
            test_type=gd.test_type or base.test_type,
            enabled_state=base.enabled_state,
            search_text=base.search_text,
        )

    def _set_page_label(self, start: int, end: int, total: int) -> None:
        self.window.plan_widget.page_label.setText(f"Showing {start}-{end} / {total}")
