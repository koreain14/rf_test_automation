from __future__ import annotations

from typing import Any, Dict, Tuple

from application.correction_profile_model import CorrectionFactorSet, CorrectionProfileDocument


_ALLOWED_TEST_TYPES = {"CHP", "PSD", "OBW", "TXP"}
_UPPER_LIMIT_COMPARATORS = {"", "upper_limit", "max", "maximum", "lte", "le"}
_LOWER_LIMIT_COMPARATORS = {"lower_limit", "min", "minimum", "gte", "ge"}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def normalize_correction_meta(meta: dict | None) -> dict[str, Any]:
    payload = _as_dict(_as_dict(meta).get("correction"))
    binding = _as_dict(payload.get("binding"))
    applies_to = [str(item or "").strip().upper() for item in (payload.get("applies_to") or []) if str(item or "").strip()]
    return {
        "enabled": bool(payload.get("enabled")),
        "mode": str(payload.get("mode") or "DIRECT").strip().upper() or "DIRECT",
        "profile_name": str(payload.get("profile_name") or "").strip(),
        "binding": {
            "type": str(binding.get("type") or "RF_PATH").strip().upper() or "RF_PATH",
            "field": str(binding.get("field") or binding.get("selected_path_field") or "antenna").strip() or "antenna",
        },
        "manual_offset_db": float(payload.get("manual_offset_db") or 0.0),
        "applies_to": applies_to,
    }


def format_correction_summary(meta: dict | None) -> str:
    correction = normalize_correction_meta(meta)
    if not correction.get("enabled"):
        return ""
    parts = ["CORR"]
    if correction.get("mode"):
        parts.append(str(correction.get("mode")))
    if correction.get("profile_name"):
        parts.append(str(correction.get("profile_name")))
    return " ".join(parts)


def resolve_bound_path(recipe_meta: dict | None, correction_meta: dict[str, Any] | None = None) -> Tuple[str, str]:
    meta = _as_dict(recipe_meta)
    rf_path = _as_dict(meta.get("rf_path"))
    correction = dict(correction_meta or {})
    binding = _as_dict(correction.get("binding"))
    field = str(binding.get("field") or "antenna").strip().lower()
    preferred = str(rf_path.get(field) or "").strip() if field else ""
    if preferred:
        return preferred, f"recipe.meta.rf_path.{field}"
    antenna = str(rf_path.get("antenna") or "").strip()
    if antenna:
        return antenna, "recipe.meta.rf_path.antenna"
    switch_path = str(rf_path.get("switch_path") or "").strip()
    if switch_path:
        return switch_path, "recipe.meta.rf_path.switch_path"
    return "", ""


def resolve_factor_set(profile: CorrectionProfileDocument | None, correction_meta: dict[str, Any], bound_path: str) -> tuple[CorrectionFactorSet | None, str]:
    if profile is None:
        return None, "PROFILE_MISSING"
    mode = str(correction_meta.get("mode") or profile.normalized_mode() or "DIRECT").strip().upper()
    if mode == "SWITCH":
        if not bound_path:
            return None, "BOUND_PATH_MISSING"
        ports = dict(profile.ports or {})
        factor_set = ports.get(bound_path)
        if factor_set is None:
            return None, "BOUND_PATH_NOT_FOUND"
        return factor_set, "OK"
    return profile.factors, "OK"


def calculate_total_correction_db(factors: CorrectionFactorSet | None, manual_offset_db: Any = 0.0) -> tuple[float, dict[str, float]]:
    payload = (factors or CorrectionFactorSet()).to_dict()
    try:
        manual_offset = float(manual_offset_db or 0.0)
    except Exception:
        manual_offset = 0.0
    breakdown = {
        "cable_loss_db": float(payload.get("cable_loss_db", 0.0) or 0.0),
        "attenuator_db": float(payload.get("attenuator_db", 0.0) or 0.0),
        "dut_cable_loss_db": float(payload.get("dut_cable_loss_db", 0.0) or 0.0),
        "switchbox_loss_db": float(payload.get("switchbox_loss_db", 0.0) or 0.0),
        "divider_loss_db": float(payload.get("divider_loss_db", 0.0) or 0.0),
        "external_gain_db": float(payload.get("external_gain_db", 0.0) or 0.0),
        "manual_offset_db": float(manual_offset),
    }
    total = (
        breakdown["cable_loss_db"]
        + breakdown["attenuator_db"]
        + breakdown["dut_cable_loss_db"]
        + breakdown["switchbox_loss_db"]
        + breakdown["divider_loss_db"]
        - breakdown["external_gain_db"]
        + breakdown["manual_offset_db"]
    )
    return round(total, 6), breakdown


def _recompute_margin_and_verdict(measured_value: float | None, limit_value: float | None, comparator: str, fallback_verdict: str) -> tuple[float | None, str]:
    measured = _as_float(measured_value)
    limit = _as_float(limit_value)
    if measured is None or limit is None:
        return None, str(fallback_verdict or "ERROR")
    comp = str(comparator or "upper_limit").strip().lower()
    if comp in _LOWER_LIMIT_COMPARATORS:
        margin = round(measured - limit, 6)
    else:
        margin = round(limit - measured, 6)
    verdict = "PASS" if margin >= 0 else "FAIL"
    return margin, verdict


def apply_correction_to_result(
    *,
    values: dict[str, Any],
    recipe_meta: dict | None,
    case,
    profile: CorrectionProfileDocument | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    out = dict(values or {})
    correction = normalize_correction_meta(recipe_meta)
    test_type = str(getattr(case, "test_type", "") or "").strip().upper()
    bound_path, binding_source = resolve_bound_path(recipe_meta, correction)
    trace: dict[str, Any] = {
        "correction_applied": False,
        "correction_enabled": bool(correction.get("enabled")),
        "correction_mode": str(correction.get("mode") or "DIRECT"),
        "correction_profile_name": str(correction.get("profile_name") or ""),
        "correction_bound_path": bound_path,
        "binding_source": binding_source,
        "raw_measured_value": _as_float(out.get("measured_value")),
        "corrected_measured_value": _as_float(out.get("measured_value")),
        "measured_value": _as_float(out.get("measured_value")),
        "limit_value": _as_float(out.get("limit_value")),
        "raw_margin_db": _as_float(out.get("margin_db")),
        "corrected_margin_db": _as_float(out.get("margin_db")),
        "margin_db": _as_float(out.get("margin_db")),
        "applied_correction_db": 0.0,
        "correction_breakdown": {},
        "reason": "DISABLED",
    }
    if not correction.get("enabled"):
        return out, trace
    if test_type not in _ALLOWED_TEST_TYPES:
        trace["reason"] = "TEST_TYPE_NOT_SUPPORTED"
        return out, trace
    applies_to = set(correction.get("applies_to") or [])
    if applies_to and test_type not in applies_to:
        trace["reason"] = "TEST_TYPE_NOT_SELECTED"
        return out, trace
    raw_measured = _as_float(out.get("measured_value"))
    if raw_measured is None:
        trace["reason"] = "MEASURED_VALUE_MISSING"
        return out, trace

    factor_set, factor_status = resolve_factor_set(profile, correction, bound_path)
    if factor_set is None:
        trace["reason"] = factor_status
        return out, trace

    total_db, breakdown = calculate_total_correction_db(factor_set, correction.get("manual_offset_db", 0.0))
    corrected_measured = round(raw_measured + total_db, 6)
    corrected_margin, corrected_verdict = _recompute_margin_and_verdict(
        corrected_measured,
        out.get("limit_value"),
        str(out.get("comparator") or "upper_limit"),
        str(out.get("verdict") or "ERROR"),
    )

    out["raw_measured_value"] = raw_measured
    out["measured_value"] = corrected_measured
    out["margin_db"] = corrected_margin
    out["verdict"] = corrected_verdict
    out["applied_correction_db"] = total_db
    out["correction_profile_name"] = str(correction.get("profile_name") or "")
    out["correction_mode"] = str(correction.get("mode") or "DIRECT")
    out["correction_bound_path"] = bound_path
    out["correction_breakdown"] = dict(breakdown)
    out["correction_applied"] = True

    trace.update(
        {
            "correction_applied": True,
            "corrected_measured_value": corrected_measured,
            "measured_value": corrected_measured,
            "corrected_margin_db": corrected_margin,
            "margin_db": corrected_margin,
            "applied_correction_db": total_db,
            "correction_breakdown": dict(breakdown),
            "reason": "APPLIED",
            "status": corrected_verdict,
            "measurement_unit": str(out.get("measurement_unit") or ""),
            "test_type": test_type,
            "case_key": str(getattr(case, "key", "") or ""),
        }
    )
    return out, trace


__all__ = [
    "apply_correction_to_result",
    "format_correction_summary",
    "normalize_correction_meta",
    "resolve_bound_path",
]
