from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any


TEST_ITEM_POOL: dict[str, dict[str, Any]] = {
    "PSD": {
        "id": "PSD",
        "display_name": "Power Spectral Density",
        "aliases": ["POWER_SPECTRAL_DENSITY"],
        "measurement_class": "spectrum",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "PSD_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_upper",
        "procedure_key": "PSD",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel", "data_rate", "voltage"],
        "unit": "dBm/MHz",
        "enabled": True,
    },
    "OBW": {
        "id": "OBW",
        "display_name": "Occupied Bandwidth",
        "aliases": ["OCCUPIED_BANDWIDTH"],
        "measurement_class": "spectrum",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "OBW_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_upper",
        "procedure_key": "OBW",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel", "voltage"],
        "unit": "MHz",
        "enabled": True,
    },
    "SP": {
        "id": "SP",
        "display_name": "Spurious",
        "aliases": ["TX_SPURIOUS", "SPURIOUS_EMISSIONS"],
        "measurement_class": "spectrum",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "SP_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_upper",
        "procedure_key": "SP",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel", "voltage"],
        "unit": "dBc",
        "enabled": True,
    },
    "RX": {
        "id": "RX",
        "display_name": "Receiver",
        "aliases": ["RX_SPURIOUS"],
        "measurement_class": "spectrum",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "RX_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_lower",
        "procedure_key": "RX",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel", "data_rate"],
        "unit": "dB",
        "enabled": True,
    },
    "TXP": {
        "id": "TXP",
        "display_name": "Conducted Power",
        "aliases": ["CHANNEL_POWER", "COND_POWER", "CONDUCTED_POWER", "TX_POWER"],
        "measurement_class": "power",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "TXP_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_upper",
        "procedure_key": "",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel", "voltage"],
        "unit": "dBm",
        "enabled": True,
        "experimental": True,
    },
    "DFS": {
        "id": "DFS",
        "display_name": "DFS",
        "aliases": [],
        "measurement_class": "dfs",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "SP_DEFAULT",
        "result_fields": ["verdict"],
        "verdict_type": "custom",
        "procedure_key": "",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel"],
        "unit": "",
        "enabled": False,
        "experimental": True,
    },
    "FE": {
        "id": "FE",
        "display_name": "Frequency Error",
        "aliases": ["FREQUENCY_ERROR"],
        "measurement_class": "frequency",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "SP_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_upper",
        "procedure_key": "",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel"],
        "unit": "ppm",
        "enabled": False,
        "experimental": True,
    },
    "BANDEDGE": {
        "id": "BANDEDGE",
        "display_name": "Band Edge",
        "aliases": ["BAND_EDGE"],
        "measurement_class": "spectrum",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "SP_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_upper",
        "procedure_key": "",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel"],
        "unit": "dBm",
        "enabled": False,
        "experimental": True,
    },
    "ACP": {
        "id": "ACP",
        "display_name": "Adjacent Channel Power",
        "aliases": [],
        "measurement_class": "spectrum",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "SP_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_upper",
        "procedure_key": "",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel"],
        "unit": "dBc",
        "enabled": False,
        "experimental": True,
    },
    "ACLR": {
        "id": "ACLR",
        "display_name": "Adjacent Channel Leakage Ratio",
        "aliases": [],
        "measurement_class": "spectrum",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "SP_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_lower",
        "procedure_key": "",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel"],
        "unit": "dB",
        "enabled": False,
        "experimental": True,
    },
    "RX_BLOCKING": {
        "id": "RX_BLOCKING",
        "display_name": "RX Blocking",
        "aliases": ["RXBLOCKING"],
        "measurement_class": "receiver",
        "required_instruments": ["analyzer"],
        "default_profile_ref": "RX_DEFAULT",
        "result_fields": ["measured_value", "limit_value", "margin_db"],
        "verdict_type": "limit_lower",
        "procedure_key": "",
        "supported_techs": ["WLAN"],
        "supported_axes": ["frequency_band", "standard", "bandwidth", "channel"],
        "unit": "dB",
        "enabled": False,
        "experimental": True,
    },
}


def _normalize_token(value: str | None) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def _aliases_map() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for canonical_id, payload in TEST_ITEM_POOL.items():
        aliases[_normalize_token(canonical_id)] = canonical_id
        for alias in payload.get("aliases") or []:
            token = _normalize_token(alias)
            if token:
                aliases[token] = canonical_id
    return aliases


def normalize_test_id(value: str | None) -> str:
    token = _normalize_token(value)
    if not token:
        return ""
    return _aliases_map().get(token, token)


def get_test_item_pool() -> dict[str, dict[str, Any]]:
    return deepcopy(TEST_ITEM_POOL)


def get_test_item_definition(test_id: str | None) -> dict[str, Any] | None:
    canonical_id = normalize_test_id(test_id)
    if not canonical_id:
        return None
    payload = TEST_ITEM_POOL.get(canonical_id)
    if payload is None:
        return None
    return deepcopy(payload)


def _supports_tech(payload: dict[str, Any], tech: str | None) -> bool:
    supported_techs = [str(item).strip().upper() for item in (payload.get("supported_techs") or []) if str(item).strip()]
    if not tech or not supported_techs:
        return True
    return str(tech).strip().upper() in supported_techs


def _supports_axis(payload: dict[str, Any], axis_name: str | None) -> bool:
    if not axis_name:
        return True
    supported_axes = [str(item).strip() for item in (payload.get("supported_axes") or []) if str(item).strip()]
    if not supported_axes:
        return True
    return str(axis_name).strip() in supported_axes


def is_selectable_test_item(test_id: str | None, *, tech: str | None = None) -> bool:
    payload = get_test_item_definition(test_id)
    if payload is None:
        return False
    if not payload.get("enabled", True):
        return False
    if not str(payload.get("procedure_key", "") or "").strip():
        return False
    return _supports_tech(payload, tech)


def list_available_test_items(
    *,
    tech: str | None = None,
    axis_name: str | None = None,
    selectable_only: bool = True,
    include_experimental: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for test_id in TEST_ITEM_POOL:
        payload = get_test_item_definition(test_id) or {}
        if not include_experimental and payload.get("experimental", False):
            continue
        if selectable_only and not is_selectable_test_item(test_id, tech=tech):
            continue
        if not _supports_tech(payload, tech):
            continue
        if not _supports_axis(payload, axis_name):
            continue
        out.append(payload)
    return out


def normalize_test_id_list(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        canonical_id = normalize_test_id(value)
        if not canonical_id or canonical_id in seen:
            continue
        seen.add(canonical_id)
        out.append(canonical_id)
    return out
