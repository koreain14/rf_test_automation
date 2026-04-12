from __future__ import annotations

import logging
from typing import Any, List, Optional

from application.plan_models import PlanFilter
from application.test_type_symbols import normalize_test_type_symbol
from ui.plan_context import PlanContext

log = logging.getLogger(__name__)


class PlanFilterPagingCoordinator:
    def __init__(self, controller):
        self.controller = controller

    @property
    def window(self):
        return self.controller.window

    @property
    def query_service(self):
        return self.controller._query_service

    def apply_filter(self) -> None:
        self.controller._current_filter = self.read_filter_from_ui()
        self.controller._group_drill_filter = None
        self.controller._current_page = 1
        self.load_group_summary()
        self.load_detail_page(page=1)

    def clear_filter(self) -> None:
        self.clear_filter_ui()
        self.controller._current_filter = PlanFilter()
        self.controller._group_drill_filter = None
        self.controller._current_page = 1
        self.load_group_summary()
        self.load_detail_page(page=1)

    def load_group_summary(self) -> None:
        ctx = self.controller._current_context()
        if not ctx:
            self.window.group_model.clear()
            return
        rows = self.query_service.query_group_summary(ctx=ctx, query=self.controller._build_query(page=1, page_size=1))
        self.window.group_model.set_rows(rows)

    def drill_down_selected_group(self) -> None:
        view = self.window.plan_widget.group_table
        model = self.window.group_model
        idxs = view.selectionModel().selectedRows() if view.selectionModel() else []
        if not idxs:
            return
        row = model.row_at(idxs[0].row())
        if not row:
            return
        self.controller._group_drill_filter = PlanFilter(
            band=row.band,
            standard=row.standard,
            bandwidth_mhz=row.bandwidth_mhz,
            test_type=row.test_type,
            enabled_state=self.controller._current_filter.enabled_state,
            search_text=self.controller._current_filter.search_text,
        )
        self.controller._current_page = 1
        self.load_detail_page(page=1)

    def load_page(self) -> None:
        self.load_detail_page(page=1)

    def load_more(self) -> None:
        self.load_detail_page(page=self.controller._current_page + 1, append=True)

    def load_detail_page(self, page: Optional[int] = None, append: bool = False) -> None:
        log.info(
            "PlanController.load_detail_page | requested_page=%s current_page=%s page_size=%s append=%s",
            page,
            self.controller._current_page,
            self.controller._page_size,
            append,
        )
        ctx = self.controller._current_context()
        if not ctx:
            self.clear_cases_view()
            return
        if page is not None:
            self.controller._current_page = max(1, int(page))
        result = self.query_service.query_page(
            ctx=ctx,
            query=self.controller._build_query(page=self.controller._current_page, page_size=self.controller._page_size),
        )
        log.info(
            "PlanController.load_detail_page | result total=%s returned=%s",
            result.get("total"),
            len(result.get("rows") or []),
        )
        rows = result["rows"]
        if append:
            current = self.window.case_model.rows()
            self.window.case_model.set_rows(current + rows)
        else:
            self.window.case_model.set_rows(rows)
        self.controller._visible_rows = self.window.case_model.rows()
        self.controller._set_page_label(result["start_index"], result["end_index"], result["total"])

    def next_page(self) -> None:
        self.load_detail_page(page=self.controller._current_page + 1)

    def prev_page(self) -> None:
        self.load_detail_page(page=max(1, self.controller._current_page - 1))

    def set_page_size(self, value: Any) -> None:
        old = self.controller._page_size
        try:
            parsed = int(value)
        except Exception:
            parsed = 200
        self.controller._page_size = max(1, min(parsed, 5000))
        self.controller._current_page = 1
        log.info(
            "PlanController.set_page_size | old=%s new=%s raw=%r reset_page=1",
            old,
            self.controller._page_size,
            value,
        )
        self.load_detail_page(page=1)

    def clear_cases_view(self) -> None:
        self.window.case_model.clear()
        self.window.group_model.clear()
        self.controller._visible_rows = []
        self.controller._set_page_label(0, 0, 0)
        self.refresh_filter_options()

    def read_filter_from_ui(self) -> PlanFilter:
        pw = self.window.plan_widget

        def _txt(obj):
            if hasattr(obj, "currentText"):
                return str(obj.currentText() or "").strip()
            return str(obj.text() or "").strip()

        def _int_or_none(obj):
            s = _txt(obj)
            if not s:
                return None
            try:
                return int(s)
            except Exception:
                return None

        return PlanFilter(
            band=_txt(pw.plan_filter_band),
            standard=_txt(pw.plan_filter_standard),
            bandwidth_mhz=_int_or_none(pw.plan_filter_bw),
            test_type=normalize_test_type_symbol(_txt(pw.plan_filter_test)),
            channel_from=_int_or_none(pw.plan_filter_channel_from),
            channel_to=_int_or_none(pw.plan_filter_channel_to),
            enabled_state=_txt(pw.plan_filter_enabled) or "ALL",
            search_text=_txt(pw.plan_filter_search),
        )

    def clear_filter_ui(self) -> None:
        pw = self.window.plan_widget
        for combo in (pw.plan_filter_band, pw.plan_filter_standard, pw.plan_filter_bw, pw.plan_filter_test, pw.plan_filter_enabled):
            combo.setCurrentIndex(0)
        for le in (pw.plan_filter_channel_from, pw.plan_filter_channel_to, pw.plan_filter_search):
            le.clear()
        self.refresh_filter_options()

    def refresh_filter_options(self) -> None:
        pw = getattr(self.window, "plan_widget", None)
        ctx = self.controller._current_context()
        if pw is None:
            return

        current_band = str(pw.plan_filter_band.currentText() or "").strip()
        current_standard = str(pw.plan_filter_standard.currentText() or "").strip()
        current_bw = str(pw.plan_filter_bw.currentText() or "").strip()

        band_values = self.available_bands_for_context(ctx)
        self.set_combo_values(pw.plan_filter_band, band_values, current_band)

        selected_band = str(pw.plan_filter_band.currentText() or "").strip()
        standard_values = self.available_standards_for_context(ctx, selected_band=selected_band)
        self.set_combo_values(pw.plan_filter_standard, standard_values, current_standard)

        bandwidth_values = [str(value) for value in self.available_bandwidths_for_context(ctx)]
        self.set_combo_values(pw.plan_filter_bw, bandwidth_values, current_bw)

    def set_combo_values(self, combo, values: List[str], current: str) -> None:
        normalized = [""]
        seen = {""}
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)

        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(normalized)
            if current and current not in normalized:
                combo.addItem(current)
            combo.setCurrentText(current if current else "")
        finally:
            combo.blockSignals(False)

    def available_bands_for_context(self, ctx: Optional[PlanContext]) -> List[str]:
        if ctx is None:
            return []
        selected_band = str(getattr(ctx.recipe, "band", "") or "").strip()
        if selected_band:
            return [selected_band]
        return [
            str(name).strip()
            for name in dict(getattr(ctx.ruleset, "bands", {}) or {}).keys()
            if str(name).strip()
        ]

    def available_standards_for_context(self, ctx: Optional[PlanContext], *, selected_band: str = "") -> List[str]:
        if ctx is None:
            return []

        recipe_meta = dict(getattr(ctx.recipe, "meta", {}) or {})
        wlan = dict(recipe_meta.get("wlan_expansion") or {})
        mode_plan = list(wlan.get("mode_plan") or [])
        standards: List[str] = []
        if mode_plan:
            for item in mode_plan:
                standard = str(item.get("standard", item.get("mode", "")) or "").strip()
                if standard and standard not in standards:
                    standards.append(standard)
            if standards:
                return standards

        if selected_band:
            band_info = dict(getattr(ctx.ruleset, "bands", {}) or {}).get(selected_band)
            if band_info is not None:
                return [
                    str(item).strip()
                    for item in list(getattr(band_info, "standards", []) or [])
                    if str(item).strip()
                ]

        selected_standard = str(getattr(ctx.recipe, "standard", "") or "").strip()
        if selected_standard:
            return [selected_standard]

        union: List[str] = []
        for band_info in dict(getattr(ctx.ruleset, "bands", {}) or {}).values():
            for item in list(getattr(band_info, "standards", []) or []):
                standard = str(item).strip()
                if standard and standard not in union:
                    union.append(standard)
        return union

    def available_bandwidths_for_context(self, ctx: Optional[PlanContext]) -> List[int]:
        if ctx is None:
            return []

        recipe_meta = dict(getattr(ctx.recipe, "meta", {}) or {})
        wlan = dict(recipe_meta.get("wlan_expansion") or {})
        mode_plan = list(wlan.get("mode_plan") or [])
        channel_plan = list(wlan.get("channel_plan") or [])
        values: List[int] = []

        for item in channel_plan:
            try:
                bw = int(item.get("bandwidth_mhz"))
            except Exception:
                continue
            if bw not in values:
                values.append(bw)

        for item in mode_plan:
            for raw_bw in (item.get("bandwidths_mhz") or []):
                try:
                    bw = int(raw_bw)
                except Exception:
                    continue
                if bw not in values:
                    values.append(bw)

        for raw_bw in list(getattr(ctx.recipe, "bandwidth_mhz", []) or []):
            try:
                bw = int(raw_bw)
            except Exception:
                continue
            if bw not in values:
                values.append(bw)

        return sorted(values)

    def on_filter_band_changed(self, _value: str) -> None:
        self.refresh_filter_options()
