from __future__ import annotations

from typing import Any, Dict


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def calculate_difference_value(measured_value: Any, limit_value: Any) -> float | None:
    measured = _as_float(measured_value)
    limit = _as_float(limit_value)
    if measured is None or limit is None:
        return None
    return round(measured - limit, 6)


def resolve_difference_unit(row: Dict[str, Any], step_data: Dict[str, Any]) -> str:
    candidates = (
        step_data.get("difference_unit"),
        step_data.get("display_measurement_unit"),
        step_data.get("measurement_unit"),
        row.get("difference_unit"),
        row.get("measurement_unit"),
    )
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def enrich_difference_fields(row: Dict[str, Any], step_data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out = dict(row or {})
    data = dict(step_data or {})

    difference_value = data.get("difference_value", out.get("difference_value"))
    if difference_value in (None, ""):
        difference_value = calculate_difference_value(out.get("measured_value"), out.get("limit_value"))

    difference_unit = resolve_difference_unit(out, data)
    comparator = str(
        data.get("comparator")
        or out.get("comparator")
        or "upper_limit"
    ).strip()

    out["difference_value"] = difference_value
    out["difference_unit"] = difference_unit
    out["comparator"] = comparator
    return out


def format_difference(value: Any, unit: str = "", *, precision: int = 2) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return ""
    text = f"{numeric:.{precision}f}"
    unit_text = str(unit or "").strip()
    return f"{text} {unit_text}".strip()


def format_difference_value(value: Any, *, precision: int = 2) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return ""
    return f"{numeric:.{precision}f}"


def format_numeric_value(value: Any, *, precision: int = 2) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return ""
    return f"{numeric:.{precision}f}"
