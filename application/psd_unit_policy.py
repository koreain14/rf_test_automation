from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PSD_UNIT_MW_PER_MHZ = "MW_PER_MHZ"
PSD_UNIT_DBM_PER_MHZ = "DBM_PER_MHZ"
PSD_CANONICAL_UNIT = PSD_UNIT_DBM_PER_MHZ
PSD_ALLOWED_UNITS = {PSD_UNIT_MW_PER_MHZ, PSD_UNIT_DBM_PER_MHZ}

PSD_METHOD_MARKER_PEAK = "MARKER_PEAK"
PSD_METHOD_AVERAGE = "AVERAGE"
PSD_ALLOWED_METHODS = {PSD_METHOD_MARKER_PEAK, PSD_METHOD_AVERAGE}

PSD_DEFAULT_LIMIT_CANONICAL = -30.0
PSD_DEFAULT_SPAN_MULTIPLIER = 2.0


def normalize_psd_result_unit(value: Any) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "": "",
        "DEFAULT": "",
        "RULESET_DEFAULT": "",
        "MW_PER_MHZ": PSD_UNIT_MW_PER_MHZ,
        "MW/MHZ": PSD_UNIT_MW_PER_MHZ,
        "MWMHZ": PSD_UNIT_MW_PER_MHZ,
        "DBM_PER_MHZ": PSD_UNIT_DBM_PER_MHZ,
        "DBM/MHZ": PSD_UNIT_DBM_PER_MHZ,
        "DBMMHZ": PSD_UNIT_DBM_PER_MHZ,
    }
    return aliases.get(text, "")


def normalize_psd_method(value: Any) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "": "",
        "DEFAULT": "",
        "RULESET_DEFAULT": "",
        "MARKER_PEAK": PSD_METHOD_MARKER_PEAK,
        "MARKER": PSD_METHOD_MARKER_PEAK,
        "PEAK": PSD_METHOD_MARKER_PEAK,
        "AVERAGE": PSD_METHOD_AVERAGE,
        "AVG": PSD_METHOD_AVERAGE,
        "TRACE_AVERAGE": PSD_METHOD_AVERAGE,
    }
    return aliases.get(text, "")


def default_psd_result_unit_for_band(band: str | None) -> str:
    normalized_band = str(band or "").strip().upper()
    if normalized_band == "6G":
        return PSD_UNIT_DBM_PER_MHZ
    if normalized_band in {"2.4G", "5G"}:
        return PSD_UNIT_MW_PER_MHZ
    return PSD_UNIT_DBM_PER_MHZ


def default_psd_method_for_ruleset(regulation: str | None = None) -> str:
    normalized_regulation = str(regulation or "").strip().upper()
    if normalized_regulation == "CE":
        return PSD_METHOD_AVERAGE
    return PSD_METHOD_MARKER_PEAK


def ruleset_default_psd_result_unit(ruleset: Any, band: str | None) -> str:
    normalized_band = str(band or "").strip()
    if ruleset is not None and normalized_band:
        try:
            bands = getattr(ruleset, "bands", {}) or {}
            band_info = bands.get(normalized_band)
            if band_info is not None:
                value = normalize_psd_result_unit(getattr(band_info, "psd_result_unit", ""))
                if value:
                    return value
        except Exception:
            pass
    return default_psd_result_unit_for_band(band)


def ruleset_default_psd_result_unit_from_file(
    *,
    ruleset_id: str | None,
    band: str | None,
    rulesets_dir: str | Path = "rulesets",
) -> str:
    normalized_ruleset_id = str(ruleset_id or "").strip()
    normalized_band = str(band or "").strip()
    if normalized_ruleset_id and normalized_band:
        path = Path(rulesets_dir) / f"{normalized_ruleset_id.lower()}.json"
        if not path.exists() and normalized_ruleset_id == "KC_WLAN":
            alt = Path(rulesets_dir) / "kc_wlan.json"
            if alt.exists():
                path = alt
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                band_info = dict((raw.get("bands") or {}).get(normalized_band) or {})
                value = normalize_psd_result_unit(band_info.get("psd_result_unit"))
                if value:
                    return value
            except Exception:
                pass
    return default_psd_result_unit_for_band(band)


def resolve_psd_result_unit(
    *,
    preset_unit: Any,
    band: str | None,
    ruleset: Any = None,
    ruleset_id: str | None = None,
    rulesets_dir: str | Path = "rulesets",
) -> str:
    explicit = normalize_psd_result_unit(preset_unit)
    if explicit:
        return explicit
    if ruleset is not None:
        return ruleset_default_psd_result_unit(ruleset, band)
    return ruleset_default_psd_result_unit_from_file(
        ruleset_id=ruleset_id,
        band=band,
        rulesets_dir=rulesets_dir,
    )


def dbm_per_mhz_to_mw_per_mhz(value_dbm_per_mhz: float) -> float:
    return 10 ** (float(value_dbm_per_mhz) / 10.0)


def mw_per_mhz_to_dbm_per_mhz(value_mw_per_mhz: float) -> float:
    value = float(value_mw_per_mhz)
    if value <= 0:
        raise ValueError("mW/MHz value must be positive to convert to dBm/MHz")
    import math

    return 10.0 * math.log10(value)


def psd_unit_label(unit: str) -> str:
    normalized = normalize_psd_result_unit(unit) or PSD_CANONICAL_UNIT
    if normalized == PSD_UNIT_MW_PER_MHZ:
        return "mW/MHz"
    return "dBm/MHz"


def psd_scpi_power_unit(unit: str) -> str:
    normalized = normalize_psd_result_unit(unit) or PSD_CANONICAL_UNIT
    if normalized == PSD_UNIT_MW_PER_MHZ:
        return "W"
    return "DBM"


def convert_psd_value(value: float, *, from_unit: str, to_unit: str) -> float:
    normalized_from = normalize_psd_result_unit(from_unit) or PSD_CANONICAL_UNIT
    normalized_to = normalize_psd_result_unit(to_unit) or PSD_CANONICAL_UNIT
    if normalized_from == normalized_to:
        return float(value)
    if normalized_from == PSD_UNIT_DBM_PER_MHZ and normalized_to == PSD_UNIT_MW_PER_MHZ:
        return dbm_per_mhz_to_mw_per_mhz(value)
    if normalized_from == PSD_UNIT_MW_PER_MHZ and normalized_to == PSD_UNIT_DBM_PER_MHZ:
        return mw_per_mhz_to_dbm_per_mhz(value)
    return float(value)


def convert_canonical_psd_value(value_dbm_per_mhz: float, display_unit: str) -> float:
    return convert_psd_value(
        value_dbm_per_mhz,
        from_unit=PSD_CANONICAL_UNIT,
        to_unit=display_unit,
    )


def build_psd_display_payload(
    *,
    canonical_value_dbm_per_mhz: float,
    display_unit: str,
) -> dict[str, Any]:
    normalized = normalize_psd_result_unit(display_unit) or PSD_CANONICAL_UNIT
    display_value = convert_canonical_psd_value(canonical_value_dbm_per_mhz, normalized)
    return {
        "canonical_value": float(canonical_value_dbm_per_mhz),
        "canonical_unit": PSD_CANONICAL_UNIT,
        "display_value": float(display_value),
        "display_unit": normalized,
        "display_label": psd_unit_label(normalized),
        "scpi_power_unit": psd_scpi_power_unit(normalized),
    }


def _normalize_psd_device_map(raw: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        if isinstance(value, dict):
            out[str(key).strip()] = dict(value)
    return out


def _ruleset_band_info(ruleset: Any, band: str | None) -> Any:
    normalized_band = str(band or "").strip()
    if not ruleset or not normalized_band:
        return None
    try:
        bands = getattr(ruleset, "bands", {}) or {}
        return bands.get(normalized_band)
    except Exception:
        return None


def _band_level_psd_config(band_info: Any) -> dict[str, Any]:
    if band_info is None:
        return {}
    raw = getattr(band_info, "psd", None)
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _device_level_psd_config(band_info: Any, device_class: str | None) -> dict[str, Any]:
    if band_info is None:
        return {}
    normalized_device_class = str(device_class or "").strip()
    device_map = _normalize_psd_device_map(getattr(band_info, "psd_by_device_class", {}) or {})
    if normalized_device_class:
        override = device_map.get(normalized_device_class)
        if isinstance(override, dict):
            return dict(override)
    return {}


def _resolve_ruleset_psd_method(ruleset: Any, band: str | None, device_class: str | None) -> str:
    band_info = _ruleset_band_info(ruleset, band)
    for source in (_device_level_psd_config(band_info, device_class), _band_level_psd_config(band_info)):
        method = normalize_psd_method(source.get("method"))
        if method:
            return method
    regulation = getattr(ruleset, "regulation", "")
    return default_psd_method_for_ruleset(regulation)


def _resolve_ruleset_psd_limit(ruleset: Any, band: str | None, device_class: str | None) -> tuple[float, str]:
    band_info = _ruleset_band_info(ruleset, band)
    result_unit = ruleset_default_psd_result_unit(ruleset, band)
    for source in (_device_level_psd_config(band_info, device_class), _band_level_psd_config(band_info)):
        limit_value = source.get("limit_value")
        limit_unit = normalize_psd_result_unit(source.get("limit_unit")) or result_unit
        try:
            if limit_value not in (None, ""):
                return float(limit_value), limit_unit
        except Exception:
            continue
    default_limit = convert_psd_value(
        PSD_DEFAULT_LIMIT_CANONICAL,
        from_unit=PSD_CANONICAL_UNIT,
        to_unit=result_unit,
    )
    return float(default_limit), result_unit


def resolve_psd_runtime_policy(
    *,
    band: str | None,
    device_class: str | None = None,
    preset_unit: Any = None,
    ruleset: Any = None,
    ruleset_id: str | None = None,
    rulesets_dir: str | Path = "rulesets",
) -> dict[str, Any]:
    result_unit = resolve_psd_result_unit(
        preset_unit=preset_unit,
        band=band,
        ruleset=ruleset,
        ruleset_id=ruleset_id,
        rulesets_dir=rulesets_dir,
    )
    if ruleset is not None:
        method = _resolve_ruleset_psd_method(ruleset, band, device_class)
        limit_value, limit_unit = _resolve_ruleset_psd_limit(ruleset, band, device_class)
    else:
        method = default_psd_method_for_ruleset("")
        limit_unit = result_unit
        limit_value = convert_psd_value(
            PSD_DEFAULT_LIMIT_CANONICAL,
            from_unit=PSD_CANONICAL_UNIT,
            to_unit=limit_unit,
        )
    canonical_limit_value = convert_psd_value(
        float(limit_value),
        from_unit=limit_unit,
        to_unit=PSD_CANONICAL_UNIT,
    )
    return {
        "method": method,
        "result_unit": result_unit,
        "limit_value": float(limit_value),
        "limit_unit": limit_unit,
        "limit_label": psd_unit_label(limit_unit),
        "canonical_limit_value": float(canonical_limit_value),
        "canonical_limit_unit": PSD_CANONICAL_UNIT,
    }
