from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from application.instrument_profile_resolver import InstrumentProfileResolver
from application.test_type_symbols import default_profile_for_test_type
from application.test_type_symbols import normalize_profile_name
from application.test_type_symbols import normalize_test_type_symbol


MEASUREMENT_SETTING_KEYS: tuple[str, ...] = (
    "span_hz",
    "span_mode",
    "span_multiplier",
    "span_min_hz",
    "rbw_hz",
    "vbw_hz",
    "span_mhz",
    "rbw_mhz",
    "vbw_mhz",
    "ref_level_dbm",
    "sweep_time_s",
    "sweep_time_ms",
    "sweep_auto",
    "avg_count",
    "average_enabled",
    "average",
    "att_db",
    "atten_db",
    "sweep_points",
    "trace_mode",
    "detector",
    "mode_settle_s",
    "post_config_settle_s",
    "post_init_settle_s",
    "measurement_wait_s",
    "fetch_poll_timeout_ms",
    "rbw_auto",
    "vbw_auto",
    "obw_average_enabled",
    "obw_average",
)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(dict(base or {}))
    for key, value in dict(override or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _normalize_detector(value: Any) -> str:
    detector = str(value or "").strip().upper()
    aliases = {
        "POSITIVE": "POSITIVE",
        "POS": "POSITIVE",
        "PEAK": "PEAK",
        "NEGATIVE": "NEGATIVE",
        "NEG": "NEGATIVE",
        "RMS": "RMS",
        "SAMPLE": "SAMPLE",
        "SAMP": "SAMPLE",
        "AVER": "AVERAGE",
        "AVERAGE": "AVERAGE",
    }
    return aliases.get(detector, detector)


def _normalize_trace_mode(value: Any) -> str:
    mode = str(value or "").strip().upper().replace(" ", "").replace("/", "_")
    aliases = {
        "MAXH": "MAX_HOLD",
        "MAXHOLD": "MAX_HOLD",
        "MAX_HOLD": "MAX_HOLD",
        "AVER": "AVERAGE",
        "AVERAGE": "AVERAGE",
        "WRIT": "CLEAR_WRITE",
        "WRITE": "CLEAR_WRITE",
        "CLEARWRITE": "CLEAR_WRITE",
        "CLEAR_WRITE": "CLEAR_WRITE",
    }
    return aliases.get(mode, mode)


def _normalize_span_mode(value: Any) -> str:
    mode = str(value or "").strip().upper().replace(" ", "").replace("-", "_")
    aliases = {
        "": "",
        "BWX2": "BW_X2",
        "BW_X2": "BW_X2",
        "BW*2": "BW_X2",
        "BW_MULTIPLIER": "BW_MULTIPLIER",
        "MULTIPLIER": "BW_MULTIPLIER",
        "FIXED": "FIXED",
    }
    return aliases.get(mode, mode)


def _normalize_numeric(value: Any) -> Any:
    if value in (None, ""):
        return value
    try:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return value
        text = str(value).strip()
        if not text:
            return value
        if any(ch in text for ch in (".", "e", "E")):
            return float(text)
        return int(text)
    except Exception:
        return value


def _normalize_bool(value: Any) -> Any:
    if value in (None, ""):
        return value
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on", "enabled"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off", "disabled"}:
        return False
    return value


def _is_present(value: Any) -> bool:
    return value not in (None, "")


def _instrument_snapshot_source(snapshot: Dict[str, Any]) -> str:
    return str(
        snapshot.get("instrument_snapshot_source")
        or snapshot.get("_instrument_settings_source")
        or "case.instrument"
    ).strip()


def _merge_instrument_snapshot_as_legacy_fallback(
    merged: Dict[str, Any],
    instrument_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    out = _deep_merge(merged, {})
    snapshot = dict(instrument_snapshot or {})
    if not snapshot:
        return out

    measurement_field_sources = dict(out.get("measurement_field_sources") or {})
    non_setting_snapshot = {
        str(key): deepcopy(value)
        for key, value in snapshot.items()
        if str(key) not in MEASUREMENT_SETTING_KEYS
    }
    out = _deep_merge(out, non_setting_snapshot)

    fallback_fields: list[str] = []
    ignored_fields: list[str] = []
    for key in MEASUREMENT_SETTING_KEYS:
        if not _is_present(snapshot.get(key)):
            continue
        if not _is_present(out.get(key)):
            out[key] = deepcopy(snapshot.get(key))
            measurement_field_sources[str(key)] = "legacy_instrument_fallback"
            fallback_fields.append(str(key))
        else:
            ignored_fields.append(str(key))

    out["instrument_snapshot_source"] = _instrument_snapshot_source(snapshot)
    out["legacy_instrument_fallback_fields"] = fallback_fields
    out["ignored_instrument_snapshot_fields"] = ignored_fields
    out["runtime_profile_precedence"] = "measurement_profile_wins_over_instrument_snapshot"
    if measurement_field_sources:
        out["measurement_field_sources"] = measurement_field_sources
    return out


def build_consumable_measurement_profile(
    *,
    test_type: str | None,
    resolved_profile: Dict[str, Any] | None = None,
    instrument_snapshot: Dict[str, Any] | None = None,
    resolver: InstrumentProfileResolver | None = None,
) -> Dict[str, Any]:
    normalized_test_type = normalize_test_type_symbol(test_type)
    resolver_obj = resolver or InstrumentProfileResolver()
    compat_profile_name = default_profile_for_test_type(normalized_test_type)
    requested_profile_name = normalize_profile_name(
        dict(resolved_profile or {}).get("profile_name")
        or dict(instrument_snapshot or {}).get("profile_name")
        or compat_profile_name
    )

    compat_base = {}
    if compat_profile_name:
        try:
            compat_base = dict(
                resolver_obj.resolve_for_test_type(compat_profile_name, normalized_test_type) or {}
            )
        except Exception:
            compat_base = {}

    requested_base = {}
    if requested_profile_name:
        try:
            requested_base = dict(
                resolver_obj.resolve_for_test_type(requested_profile_name, normalized_test_type) or {}
            )
        except Exception:
            requested_base = {}

    merged = _deep_merge(compat_base, requested_base)
    merged = _deep_merge(merged, dict(resolved_profile or {}))
    merged = _merge_instrument_snapshot_as_legacy_fallback(
        merged,
        dict(instrument_snapshot or {}),
    )
    measurement_field_sources = dict(merged.get("measurement_field_sources") or {})

    if merged.get("detector") not in (None, ""):
        merged["detector"] = _normalize_detector(merged.get("detector"))
    if merged.get("trace_mode") not in (None, ""):
        merged["trace_mode"] = _normalize_trace_mode(merged.get("trace_mode"))
    if merged.get("span_mode") not in (None, ""):
        merged["span_mode"] = _normalize_span_mode(merged.get("span_mode"))

    for key in (
        "span_hz",
        "span_multiplier",
        "span_min_hz",
        "rbw_hz",
        "vbw_hz",
        "span_mhz",
        "rbw_mhz",
        "vbw_mhz",
        "ref_level_dbm",
        "sweep_time_s",
        "sweep_time_ms",
        "avg_count",
        "att_db",
        "atten_db",
        "sweep_points",
        "mode_settle_s",
        "post_config_settle_s",
        "post_init_settle_s",
        "measurement_wait_s",
        "fetch_poll_timeout_ms",
    ):
        if key in merged:
            merged[key] = _normalize_numeric(merged.get(key))

    for key in (
        "average_enabled",
        "average",
        "sweep_auto",
        "rbw_auto",
        "vbw_auto",
        "obw_average_enabled",
        "obw_average",
    ):
        if key in merged:
            merged[key] = _normalize_bool(merged.get(key))

    if merged.get("sweep_time_s") in (None, "") and merged.get("sweep_time_ms") not in (None, ""):
        try:
            merged["sweep_time_s"] = float(merged.get("sweep_time_ms")) / 1000.0
        except Exception:
            pass

    if requested_profile_name and merged.get("profile_name") in (None, ""):
        merged["profile_name"] = requested_profile_name
    elif compat_profile_name and merged.get("profile_name") in (None, ""):
        merged["profile_name"] = compat_profile_name
    if normalized_test_type and merged.get("test_type") in (None, ""):
        merged["test_type"] = normalized_test_type
    if measurement_field_sources:
        merged["measurement_field_sources"] = measurement_field_sources
    merged["requested_profile_name"] = requested_profile_name
    merged["compat_profile_name"] = compat_profile_name
    merged["measurement_profile_precedence"] = "measurement_profile_wins_over_instrument_snapshot"
    merged["measurement_profile_precedence_detail"] = {
        "requested_profile_name": requested_profile_name,
        "compat_profile_name": compat_profile_name,
        "instrument_snapshot_source": merged.get("instrument_snapshot_source", ""),
        "legacy_instrument_fallback_fields": list(merged.get("legacy_instrument_fallback_fields") or []),
        "ignored_instrument_snapshot_fields": list(merged.get("ignored_instrument_snapshot_fields") or []),
    }

    return merged
