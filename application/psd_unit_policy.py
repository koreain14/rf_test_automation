from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PSD_UNIT_MW_PER_MHZ = "MW_PER_MHZ"
PSD_UNIT_DBM_PER_MHZ = "DBM_PER_MHZ"
PSD_CANONICAL_UNIT = PSD_UNIT_DBM_PER_MHZ
PSD_ALLOWED_UNITS = {PSD_UNIT_MW_PER_MHZ, PSD_UNIT_DBM_PER_MHZ}


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


def default_psd_result_unit_for_band(band: str | None) -> str:
    normalized_band = str(band or "").strip().upper()
    if normalized_band == "6G":
        return PSD_UNIT_DBM_PER_MHZ
    if normalized_band in {"2.4G", "5G"}:
        return PSD_UNIT_MW_PER_MHZ
    return PSD_UNIT_DBM_PER_MHZ


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


def convert_canonical_psd_value(value_dbm_per_mhz: float, display_unit: str) -> float:
    normalized = normalize_psd_result_unit(display_unit) or PSD_CANONICAL_UNIT
    if normalized == PSD_UNIT_MW_PER_MHZ:
        return dbm_per_mhz_to_mw_per_mhz(value_dbm_per_mhz)
    return float(value_dbm_per_mhz)


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
    }
