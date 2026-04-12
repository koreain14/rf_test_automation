from __future__ import annotations

from typing import Any, Dict, List

from application.result_compare_key import build_compare_identity_key
from application.result_row_contract import normalize_compare_row, normalize_result_row


class PlanResultService:
    def __init__(self, owner):
        self.owner = owner

    @property
    def run_repo(self):
        return self.owner.run_repo

    def list_runs_for_results(self, project_id: str, limit: int = 100):
        return self.run_repo.list_recent_runs(project_id=project_id, limit=limit)

    def get_results_page(
        self,
        project_id: str,
        run_id: str,
        status_filter: str = "ALL",
        offset: int = 0,
        limit: int = 5000,
    ):
        rows = self.run_repo.list_results(
            project_id=project_id,
            run_id=run_id,
            status=status_filter,
            limit=limit,
        )
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(normalize_result_row(r))
        return out

    def get_comparable_results(self, project_id: str, run_a: str, run_b: str) -> List[Dict[str, Any]]:
        rows_a = self.get_results_page(project_id=project_id, run_id=run_a, status_filter="ALL", offset=0, limit=5000)
        rows_b = self.get_results_page(project_id=project_id, run_id=run_b, status_filter="ALL", offset=0, limit=5000)

        map_a = {build_compare_identity_key(r): r for r in rows_a}
        map_b = {build_compare_identity_key(r): r for r in rows_b}

        out: List[Dict[str, Any]] = []
        for key in sorted(set(map_a.keys()) | set(map_b.keys())):
            a = map_a.get(key, {})
            b = map_b.get(key, {})
            margin_a = a.get("margin_db")
            margin_b = b.get("margin_db")
            difference_a = a.get("difference_value")
            difference_b = b.get("difference_value")
            measured_a = a.get("measured_value")
            measured_b = b.get("measured_value")
            difference_unit_a = str(a.get("difference_unit", "") or "")
            difference_unit_b = str(b.get("difference_unit", "") or "")
            measured_unit_a = str(a.get("measurement_unit", "") or difference_unit_a)
            measured_unit_b = str(b.get("measurement_unit", "") or difference_unit_b)
            if difference_unit_a and difference_unit_b and difference_unit_a == difference_unit_b:
                try:
                    delta_difference = round(float(difference_b) - float(difference_a), 3)
                except Exception:
                    delta_difference = ""
                delta_difference_unit = difference_unit_a
            else:
                delta_difference = ""
                delta_difference_unit = ""
            if measured_unit_a and measured_unit_b and measured_unit_a == measured_unit_b:
                try:
                    delta_value = round(float(measured_b) - float(measured_a), 3)
                except Exception:
                    delta_value = ""
                delta_unit = measured_unit_a
            else:
                delta_value = ""
                delta_unit = ""

            status_a = a.get("status", "MISSING") if a else "MISSING"
            status_b = b.get("status", "MISSING") if b else "MISSING"
            row = {
                "test_key": key[0],
                "test_type": key[1],
                "band": key[2],
                "standard": key[3],
                "channel": key[4],
                "bw_mhz": key[5],
                "data_rate": a.get("data_rate") or b.get("data_rate") or "",
                "voltage_condition": a.get("voltage_condition") or b.get("voltage_condition") or "",
                "status_a": status_a,
                "status_b": status_b,
                "margin_a": "" if margin_a is None else margin_a,
                "margin_b": "" if margin_b is None else margin_b,
                "difference_a": "" if difference_a is None else difference_a,
                "difference_b": "" if difference_b is None else difference_b,
                "difference_unit": difference_unit_a or difference_unit_b,
                "measured_a": "" if measured_a is None else measured_a,
                "measured_b": "" if measured_b is None else measured_b,
                "unit": measured_unit_a or measured_unit_b or difference_unit_a or difference_unit_b,
                "delta_value": delta_value,
                "delta_unit": delta_unit,
                "delta_difference": delta_difference,
                "delta_difference_unit": delta_difference_unit,
                "limit_a": a.get("limit_value", ""),
                "limit_b": b.get("limit_value", ""),
                "comparator_a": a.get("comparator", ""),
                "comparator_b": b.get("comparator", ""),
                "screenshot_path_a": a.get("screenshot_path", ""),
                "screenshot_path_b": b.get("screenshot_path", ""),
                "screenshot_abs_path_a": a.get("screenshot_abs_path", ""),
                "screenshot_abs_path_b": b.get("screenshot_abs_path", ""),
                "has_screenshot_a": bool(a.get("has_screenshot")),
                "has_screenshot_b": bool(b.get("has_screenshot")),
                "nominal_voltage_v_a": a.get("nominal_voltage_v"),
                "nominal_voltage_v_b": b.get("nominal_voltage_v"),
                "target_voltage_v_a": a.get("target_voltage_v"),
                "target_voltage_v_b": b.get("target_voltage_v"),
                "target_voltage_v_display_a": a.get("target_voltage_v"),
                "target_voltage_v_display_b": b.get("target_voltage_v"),
                "correction_profile_name_a": a.get("correction_profile_name", ""),
                "correction_profile_name_b": b.get("correction_profile_name", ""),
                "correction_bound_path_a": a.get("correction_bound_path", ""),
                "correction_bound_path_b": b.get("correction_bound_path", ""),
                "changed": (
                    (status_a != status_b)
                    or (delta_value != "" and delta_value != 0)
                    or (delta_difference != "" and delta_difference != 0)
                ),
            }
            out.append(normalize_compare_row(row))
        return out
