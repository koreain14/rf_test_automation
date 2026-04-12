from __future__ import annotations

from typing import Any, Dict, Tuple

from application.test_type_symbols import normalize_test_type_symbol


RESULT_ROW_FIELDS: Tuple[str, ...] = (
    "result_id",
    "status",
    "test_type",
    "band",
    "standard",
    "data_rate",
    "group",
    "channel",
    "bw_mhz",
    "margin_db",
    "difference_value",
    "difference_unit",
    "comparator",
    "measurement_unit",
    "measurement_method",
    "measurement_profile_name",
    "measurement_profile_source",
    "measured_value",
    "limit_value",
    "raw_measured_value",
    "applied_correction_db",
    "correction_profile_name",
    "correction_mode",
    "correction_bound_path",
    "correction_breakdown",
    "correction_applied",
    "screenshot_path",
    "screenshot_abs_path",
    "has_screenshot",
    "voltage_condition",
    "nominal_voltage_v",
    "target_voltage_v",
    "last_step_data",
    "reason",
    "test_key",
)


COMPARE_ROW_FIELDS: Tuple[str, ...] = (
    "test_key",
    "test_type",
    "band",
    "standard",
    "channel",
    "bw_mhz",
    "data_rate",
    "voltage_condition",
    "status_a",
    "status_b",
    "margin_a",
    "margin_b",
    "difference_a",
    "difference_b",
    "difference_unit",
    "measured_a",
    "measured_b",
    "unit",
    "delta_value",
    "delta_unit",
    "delta_difference",
    "delta_difference_unit",
    "limit_a",
    "limit_b",
    "comparator_a",
    "comparator_b",
    "screenshot_path_a",
    "screenshot_path_b",
    "screenshot_abs_path_a",
    "screenshot_abs_path_b",
    "has_screenshot_a",
    "has_screenshot_b",
    "nominal_voltage_v_a",
    "nominal_voltage_v_b",
    "target_voltage_v_a",
    "target_voltage_v_b",
    "target_voltage_v_display_a",
    "target_voltage_v_display_b",
    "correction_profile_name_a",
    "correction_profile_name_b",
    "correction_bound_path_a",
    "correction_bound_path_b",
    "changed",
)


_RESULT_DEFAULTS: Dict[str, Any] = {
    "result_id": None,
    "status": "",
    "test_type": "",
    "band": "",
    "standard": "",
    "data_rate": "",
    "group": "",
    "channel": None,
    "bw_mhz": None,
    "margin_db": None,
    "difference_value": None,
    "difference_unit": "",
    "comparator": "",
    "measurement_unit": "",
    "measurement_method": "",
    "measurement_profile_name": "",
    "measurement_profile_source": "",
    "measured_value": None,
    "limit_value": None,
    "raw_measured_value": None,
    "applied_correction_db": None,
    "correction_profile_name": "",
    "correction_mode": "",
    "correction_bound_path": "",
    "correction_breakdown": {},
    "correction_applied": False,
    "screenshot_path": "",
    "screenshot_abs_path": "",
    "has_screenshot": False,
    "voltage_condition": "",
    "nominal_voltage_v": None,
    "target_voltage_v": None,
    "last_step_data": {},
    "reason": "",
    "test_key": "",
}


_COMPARE_DEFAULTS: Dict[str, Any] = {
    "test_key": "",
    "test_type": "",
    "band": "",
    "standard": "",
    "channel": "",
    "bw_mhz": "",
    "data_rate": "",
    "voltage_condition": "",
    "status_a": "MISSING",
    "status_b": "MISSING",
    "margin_a": "",
    "margin_b": "",
    "difference_a": "",
    "difference_b": "",
    "difference_unit": "",
    "measured_a": "",
    "measured_b": "",
    "unit": "",
    "delta_value": "",
    "delta_unit": "",
    "delta_difference": "",
    "delta_difference_unit": "",
    "limit_a": "",
    "limit_b": "",
    "comparator_a": "",
    "comparator_b": "",
    "screenshot_path_a": "",
    "screenshot_path_b": "",
    "screenshot_abs_path_a": "",
    "screenshot_abs_path_b": "",
    "has_screenshot_a": False,
    "has_screenshot_b": False,
    "nominal_voltage_v_a": None,
    "nominal_voltage_v_b": None,
    "target_voltage_v_a": None,
    "target_voltage_v_b": None,
    "target_voltage_v_display_a": None,
    "target_voltage_v_display_b": None,
    "correction_profile_name_a": "",
    "correction_profile_name_b": "",
    "correction_bound_path_a": "",
    "correction_bound_path_b": "",
    "changed": False,
}


def result_row_fields() -> Tuple[str, ...]:
    return RESULT_ROW_FIELDS



def compare_row_fields() -> Tuple[str, ...]:
    return COMPARE_ROW_FIELDS



def normalize_result_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(_RESULT_DEFAULTS)
    row.update({k: raw.get(k, _RESULT_DEFAULTS[k]) for k in RESULT_ROW_FIELDS if k in raw})
    row["status"] = str(row.get("status", "") or "")
    row["test_type"] = normalize_test_type_symbol(row.get("test_type", ""))
    row["band"] = str(row.get("band", "") or "")
    row["standard"] = str(row.get("standard", "") or "")
    row["data_rate"] = str(row.get("data_rate", "") or "")
    row["group"] = str(row.get("group", "") or "")
    row["difference_unit"] = str(row.get("difference_unit", "") or "")
    row["comparator"] = str(row.get("comparator", "") or "")
    row["measurement_unit"] = str(row.get("measurement_unit", "") or "")
    row["measurement_method"] = str(row.get("measurement_method", "") or "")
    row["measurement_profile_name"] = str(row.get("measurement_profile_name", "") or "")
    row["measurement_profile_source"] = str(row.get("measurement_profile_source", "") or "")
    row["correction_profile_name"] = str(row.get("correction_profile_name", "") or "")
    row["correction_mode"] = str(row.get("correction_mode", "") or "")
    row["correction_bound_path"] = str(row.get("correction_bound_path", "") or "")
    row["correction_breakdown"] = dict(row.get("correction_breakdown") or {})
    row["correction_applied"] = bool(row.get("correction_applied"))
    row["screenshot_path"] = str(row.get("screenshot_path", "") or "")
    row["screenshot_abs_path"] = str(row.get("screenshot_abs_path", "") or "")
    row["has_screenshot"] = bool(row.get("has_screenshot"))
    row["voltage_condition"] = str(row.get("voltage_condition", "") or "")
    row["last_step_data"] = dict(row.get("last_step_data") or {})
    row["reason"] = str(row.get("reason", "") or "")
    row["test_key"] = str(row.get("test_key", "") or "")
    return row



def normalize_compare_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(_COMPARE_DEFAULTS)
    row.update({k: raw.get(k, _COMPARE_DEFAULTS[k]) for k in COMPARE_ROW_FIELDS if k in raw})
    for key in (
        "test_key",
        "test_type",
        "band",
        "standard",
        "data_rate",
        "voltage_condition",
        "difference_unit",
        "unit",
        "delta_unit",
        "delta_difference_unit",
        "comparator_a",
        "comparator_b",
        "screenshot_path_a",
        "screenshot_path_b",
        "screenshot_abs_path_a",
        "screenshot_abs_path_b",
        "correction_profile_name_a",
        "correction_profile_name_b",
        "correction_bound_path_a",
        "correction_bound_path_b",
    ):
        row[key] = str(row.get(key, "") or "")
    row["status_a"] = str(row.get("status_a", "MISSING") or "MISSING")
    row["status_b"] = str(row.get("status_b", "MISSING") or "MISSING")
    row["has_screenshot_a"] = bool(row.get("has_screenshot_a"))
    row["has_screenshot_b"] = bool(row.get("has_screenshot_b"))
    row["changed"] = bool(row.get("changed"))
    return row


__all__ = [
    "RESULT_ROW_FIELDS",
    "COMPARE_ROW_FIELDS",
    "result_row_fields",
    "compare_row_fields",
    "normalize_result_row",
    "normalize_compare_row",
]
