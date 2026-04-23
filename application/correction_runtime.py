from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Dict, Tuple

from application.correction_profile_model import CorrectionFactorSet, CorrectionProfileDocument
from application.test_type_symbols import normalize_test_type_symbol


CORRECTION_CAPABILITY: dict[str, str] = {
    "CHP": "DIRECT_DB",
    "TXP": "DIRECT_DB",
    "PSD": "PSD_CANONICAL_DB",
    "OBW": "DIRECT_DB",
    "RX": "DIRECT_DB",
}
_ALLOWED_TEST_TYPES = set(CORRECTION_CAPABILITY)
_UPPER_LIMIT_COMPARATORS = {"", "upper_limit", "max", "maximum", "lte", "le"}
_LOWER_LIMIT_COMPARATORS = {"lower_limit", "min", "minimum", "gte", "ge"}
_TX_TEST_TYPES = {"CHP", "TXP", "PSD", "OBW", "SP"}
_RX_TEST_TYPES = {"RX"}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "yes", "y", "on", "enabled"}


def _normalize_factor_id(value: Any) -> str:
    return str(value or "").strip()


def _normalize_port_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_port_factor_map(value: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(value, dict):
        return out
    for key, raw in value.items():
        normalized_key = _normalize_port_key(key)
        normalized_value = _normalize_factor_id(raw)
        if not normalized_key:
            continue
        out[normalized_key] = normalized_value
    return out


def _normalize_applies_to(values: Iterable[str] | None) -> list[str]:
    return filter_supported_correction_test_types(values)


def correction_capability_for_test_type(test_type: str | None) -> str:
    normalized = normalize_test_type_symbol(test_type)
    return str(CORRECTION_CAPABILITY.get(normalized, ""))


def filter_supported_correction_test_types(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        normalized = normalize_test_type_symbol(value)
        if not normalized or normalized in seen:
            continue
        if normalized not in CORRECTION_CAPABILITY:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def is_legacy_profile_correction(payload: dict[str, Any]) -> bool:
    mode = str(payload.get("mode") or "").strip().upper()
    return bool(payload.get("profile_name")) or mode in {"DIRECT", "SWITCH"}


def normalize_correction_meta(meta: dict | None) -> dict[str, Any]:
    payload = _as_dict(_as_dict(meta).get("correction"))
    binding = _as_dict(payload.get("binding"))
    applies_to = _normalize_applies_to(payload.get("applies_to") or [])
    rx_enabled = _as_bool(payload.get("rx_enabled")) or ("RX" in applies_to)
    manual_override_payload = _as_dict(payload.get("manual_override"))
    switch_port_factors = _normalize_port_factor_map(payload.get("switch_port_factors"))
    raw_mode = str(payload.get("mode") or "").strip()
    normalized_mode = raw_mode.lower()
    legacy = is_legacy_profile_correction(payload)

    if legacy:
        mode = raw_mode.upper() or "DIRECT"
        legacy_profile_name = str(payload.get("profile_name") or "").strip()
        return {
            "enabled": bool(payload.get("enabled")),
            "mode": mode,
            "apply_model": "auto",
            "tx_base_factor": "",
            "rx_base_factor": "",
            "switch_port_factors": {},
            "manual_override": {
                "enabled": False,
                "set_id": "",
            },
            "binding": {
                "type": str(binding.get("type") or "RF_PATH").strip().upper() or "RF_PATH",
                "field": str(binding.get("field") or binding.get("selected_path_field") or "antenna").strip() or "antenna",
            },
            "manual_offset_db": float(payload.get("manual_offset_db") or 0.0),
            "applies_to": applies_to,
            "rx_enabled": rx_enabled,
            "profile_name": legacy_profile_name,
            "storage_kind": "legacy_profile",
            "legacy_profile_name": legacy_profile_name,
            "version": max(1, _as_int(payload.get("version"), 1)),
        }

    mode = normalized_mode if normalized_mode in {"instrument", "off"} else ("instrument" if bool(payload.get("enabled")) else "off")
    apply_model = str(payload.get("apply_model") or "auto").strip().lower()
    if apply_model not in {"auto", "manual"}:
        apply_model = "auto"
    manual_override_enabled = bool(manual_override_payload.get("enabled")) or apply_model == "manual"
    manual_override_set_id = _normalize_factor_id(
        manual_override_payload.get("set_id")
        or manual_override_payload.get("resolved_set")
        or payload.get("resolved_set")
    )
    return {
        "enabled": bool(payload.get("enabled")),
        "mode": mode,
        "apply_model": apply_model,
        "tx_base_factor": _normalize_factor_id(payload.get("tx_base_factor")),
        "rx_base_factor": _normalize_factor_id(payload.get("rx_base_factor")),
        "switch_port_factors": switch_port_factors,
        "manual_override": {
            "enabled": manual_override_enabled,
            "set_id": manual_override_set_id,
        },
        "binding": {
            "type": str(binding.get("type") or "RF_PATH").strip().upper() or "RF_PATH",
            "field": str(binding.get("field") or binding.get("selected_path_field") or "antenna").strip() or "antenna",
        },
        "manual_offset_db": float(payload.get("manual_offset_db") or 0.0),
        "applies_to": applies_to,
        "rx_enabled": rx_enabled,
        "profile_name": "",
        "storage_kind": "instrument_factor",
        "legacy_profile_name": "",
        "version": max(1, _as_int(payload.get("version"), 1)),
    }


def format_correction_summary(meta: dict | None) -> str:
    correction = normalize_correction_meta(meta)
    if not correction.get("enabled"):
        return ""
    if correction.get("storage_kind") == "legacy_profile":
        parts = ["CORR"]
        if correction.get("mode"):
            parts.append(str(correction.get("mode")))
        if correction.get("profile_name"):
            parts.append(str(correction.get("profile_name")))
        return " ".join(parts)

    parts = ["CORR", str(correction.get("mode") or "instrument").upper()]
    if str(correction.get("apply_model") or "auto").lower() == "manual":
        set_id = str(((correction.get("manual_override") or {}).get("set_id")) or "").strip()
        parts.append("MANUAL")
        if set_id:
            parts.append(set_id)
        return " ".join(parts)

    tx_base = str(correction.get("tx_base_factor") or "").strip()
    rx_base = str(correction.get("rx_base_factor") or "").strip()
    parts.append("AUTO")
    if tx_base or rx_base:
        parts.append(f"TX:{tx_base or '-'}")
        parts.append(f"RX:{rx_base or '-'}")
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


def correction_measurement_role_for_test_type(test_type: str | None) -> str:
    normalized = normalize_test_type_symbol(test_type)
    if normalized in _RX_TEST_TYPES:
        return "RX"
    if normalized in _TX_TEST_TYPES:
        return "TX"
    return ""


def resolve_runtime_correction(recipe_meta: dict | None, case) -> dict[str, Any]:
    correction = normalize_correction_meta(recipe_meta)
    bound_path, binding_source = resolve_bound_path(recipe_meta, correction)
    test_type = normalize_test_type_symbol(getattr(case, "test_type", ""))
    measurement_role = correction_measurement_role_for_test_type(test_type)
    port_map = dict(correction.get("switch_port_factors") or {})
    port_factor = port_map.get(_normalize_port_key(bound_path), "")
    apply_model = str(correction.get("apply_model") or "auto").strip().lower()
    manual_override = _as_dict(correction.get("manual_override"))
    resolved_factors: list[str] = []
    resolved_sets: list[str] = []
    reason = "DISABLED"
    rx_correction_enabled = _as_bool(correction.get("rx_enabled"))
    role_correction_enabled = measurement_role == "TX" or (measurement_role == "RX" and rx_correction_enabled)

    if not correction.get("enabled"):
        reason = "DISABLED"
    elif correction.get("storage_kind") == "legacy_profile":
        reason = "LEGACY_PROFILE_MODE"
    elif str(correction.get("mode") or "instrument").strip().lower() != "instrument":
        reason = "MODE_OFF"
    elif measurement_role == "RX" and not rx_correction_enabled:
        reason = "RX_CORRECTION_DISABLED"
    elif not role_correction_enabled:
        reason = "MEASUREMENT_ROLE_NOT_SUPPORTED"
    elif apply_model == "manual" or _as_bool(manual_override.get("enabled")):
        set_id = _normalize_factor_id(manual_override.get("set_id"))
        if set_id:
            resolved_sets = [set_id]
            resolved_factors = [set_id]
            reason = "READY"
        else:
            reason = "MANUAL_OVERRIDE_MISSING"
    else:
        base_factor = ""
        if measurement_role == "TX":
            base_factor = _normalize_factor_id(correction.get("tx_base_factor"))
        elif measurement_role == "RX":
            base_factor = _normalize_factor_id(correction.get("rx_base_factor"))

        for candidate in (base_factor, _normalize_factor_id(port_factor)):
            if candidate and candidate not in resolved_factors:
                resolved_factors.append(candidate)
        if resolved_factors:
            reason = "READY"
        else:
            reason = "NO_FACTORS_RESOLVED"

    resolved_set = "+".join(resolved_factors) if len(resolved_factors) > 1 else (resolved_factors[0] if resolved_factors else "")
    if resolved_set and not resolved_sets:
        resolved_sets = [resolved_set]

    return {
        "enabled": bool(correction.get("enabled")),
        "mode": str(correction.get("mode") or ""),
        "storage_kind": str(correction.get("storage_kind") or ""),
        "apply_model": apply_model,
        "test_type": test_type,
        "measurement_role": measurement_role,
        "current_measurement": measurement_role or (test_type or ""),
        "current_path": bound_path,
        "binding_source": binding_source,
        "tx_base_factor": _normalize_factor_id(correction.get("tx_base_factor")),
        "rx_base_factor": _normalize_factor_id(correction.get("rx_base_factor")),
        "rx_enabled": rx_correction_enabled,
        "switch_port_factor": _normalize_factor_id(port_factor),
        "switch_port_factors": port_map,
        "resolved_factors": resolved_factors,
        "resolved_set": resolved_set,
        "resolved_sets": resolved_sets,
        "manual_override": {
            "enabled": _as_bool(manual_override.get("enabled")),
            "set_id": _normalize_factor_id(manual_override.get("set_id")),
        },
        "reason": reason,
    }


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
    test_type = normalize_test_type_symbol(getattr(case, "test_type", ""))
    bound_path, binding_source = resolve_bound_path(recipe_meta, correction)
    runtime_resolution = resolve_runtime_correction(recipe_meta, case)
    trace: dict[str, Any] = {
        "correction_applied": False,
        "correction_enabled": bool(correction.get("enabled")),
        "correction_mode": str(correction.get("mode") or ""),
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
        "resolved_factors": list(runtime_resolution.get("resolved_factors") or []),
        "resolved_set": str(runtime_resolution.get("resolved_set") or ""),
        "resolved_sets": list(runtime_resolution.get("resolved_sets") or []),
        "measurement_role": str(runtime_resolution.get("measurement_role") or ""),
        "rx_enabled": _as_bool(correction.get("rx_enabled")),
        "apply_model": str(runtime_resolution.get("apply_model") or ""),
        "reason": "DISABLED",
    }
    if not correction.get("enabled"):
        return out, trace

    if correction.get("storage_kind") == "instrument_factor":
        trace.update(
            {
                "correction_applied": bool(runtime_resolution.get("reason") == "READY"),
                "correction_mode": str(correction.get("mode") or "instrument").upper(),
                "correction_breakdown": {
                    "storage_kind": "instrument_factor",
                    "apply_model": runtime_resolution.get("apply_model", ""),
                    "measurement_role": runtime_resolution.get("measurement_role", ""),
                    "current_path": runtime_resolution.get("current_path", ""),
                    "resolved_factors": list(runtime_resolution.get("resolved_factors") or []),
                    "resolved_set": runtime_resolution.get("resolved_set", ""),
                    "resolved_sets": list(runtime_resolution.get("resolved_sets") or []),
                    "switch_port_factor": runtime_resolution.get("switch_port_factor", ""),
                },
                "reason": str(runtime_resolution.get("reason") or "DISABLED"),
                "status": str(out.get("verdict") or ""),
                "measurement_unit": str(out.get("measurement_unit") or ""),
                "test_type": test_type,
                "case_key": str(getattr(case, "key", "") or ""),
            }
        )
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
    "correction_capability_for_test_type",
    "correction_measurement_role_for_test_type",
    "filter_supported_correction_test_types",
    "format_correction_summary",
    "normalize_correction_meta",
    "resolve_bound_path",
    "resolve_runtime_correction",
]
