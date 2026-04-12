from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

from domain.ruleset_models import collect_ruleset_test_types, project_ruleset_test_contracts

_TEMPLATE_LABELS = {
    "WLAN_TEMPLATE": "WLAN (KC)",
    "MINIMAL_TEMPLATE": "Minimal",
    "CUSTOM_EMPTY": "Custom (empty)",
}


def get_available_templates() -> List[Dict[str, str]]:
    return [
        {"id": "WLAN_TEMPLATE", "label": _TEMPLATE_LABELS["WLAN_TEMPLATE"]},
        {"id": "MINIMAL_TEMPLATE", "label": _TEMPLATE_LABELS["MINIMAL_TEMPLATE"]},
        {"id": "CUSTOM_EMPTY", "label": _TEMPLATE_LABELS["CUSTOM_EMPTY"]},
    ]


def load_template(template_id: str) -> Dict[str, Any]:
    normalized = str(template_id or "").strip().upper()
    if normalized == "WLAN_TEMPLATE":
        return _load_wlan_template()
    if normalized == "MINIMAL_TEMPLATE":
        return _load_minimal_template()
    return _load_custom_empty_template()


def _load_wlan_template() -> Dict[str, Any]:
    template_path = Path(__file__).resolve().parent.parent / "rulesets" / "kc_wlan.json"
    try:
        raw = json.loads(template_path.read_text(encoding="utf-8"))
    except Exception:
        raw = _fallback_wlan_template()
    payload = deepcopy(raw)
    payload["id"] = "NEW_WLAN_RULESET"
    payload["version"] = "2026.02"
    payload["test_contracts"] = project_ruleset_test_contracts(
        payload.get("test_contracts") or {},
        tests_supported=collect_ruleset_test_types(payload),
    )
    return payload


def _load_minimal_template() -> Dict[str, Any]:
    payload = {
        "id": "MINIMAL_RULESET",
        "version": "2026.02",
        "schema_version": 2,
        "regulation": "KC",
        "tech": "WLAN",
        "case_dimensions": {
            "base": ["test_type", "frequency_band", "channel"],
            "optional_axes": [],
            "dimensions": {
                "frequency_band": {
                    "type": "enum",
                    "source": "bands",
                    "maps_to": "band",
                    "values": ["2.4G"],
                },
                "channel": {
                    "type": "numeric",
                    "source": "channel_groups",
                    "maps_to": "channel",
                },
            },
        },
        "bands": {
            "2.4G": {
                "psd_result_unit": "MW_PER_MHZ",
                "psd_policy": {
                    "method": "MARKER_PEAK",
                    "result_unit": "MW_PER_MHZ",
                    "comparator": "upper_limit",
                    "limit": {
                        "value": 10.0,
                        "unit": "MW_PER_MHZ",
                    },
                },
                "psd": {
                    "method": "MARKER_PEAK",
                    "limit_value": 10.0,
                    "limit_unit": "MW_PER_MHZ",
                },
                "standards": ["802.11n"],
                "tests_supported": ["PSD"],
                "channel_groups": {
                    "DEFAULT": {
                        "channels": [1],
                        "dfs_required": False,
                        "representatives": {"LOW": 1},
                    }
                },
            }
        },
        "instrument_profiles": {
            "PSD_DEFAULT": {
                "rbw_hz": 100000,
                "vbw_hz": 300000,
                "detector": "RMS",
                "trace_mode": "AVERAGE",
            }
        },
        "instrument_profile_refs": {
            "PSD": "PSD_DEFAULT",
        },
        "plan_modes": {
            "Quick": {"channel_policy": "REPRESENTATIVES_ONLY"},
            "Full": {"channel_policy": "ALL_CHANNELS"},
        },
        "voltage_policy": {
            "enabled": False,
            "mode": "PERCENT_OF_NOMINAL",
            "nominal_source": "preset.nominal_voltage_v",
            "apply_to": [],
            "settle_time_ms": 0,
            "fallback_policy": "WARN_AND_CONTINUE",
            "levels": [],
        },
        "data_rate_policy": {
            "enabled": False,
            "apply_to": [],
            "non_applicable_mode": "OMIT",
            "by_standard": {},
        },
        "test_labels": {
            "PSD": "Power Spectral Density (PSD)",
        },
        "test_contracts": {
            "power_spectral_density": {
                "id": "power_spectral_density",
                "name": "Power Spectral Density",
                "apply_to_test_type": "PSD",
                "measurement_class": "spectrum",
                "default_profile_ref": "PSD_DEFAULT",
                "default_profile": "PSD_DEFAULT",
                "required_instruments": ["analyzer"],
                "result_fields": ["measured_psd"],
                "unit": "dBm/MHz",
                "unit_source": "informational_only",
                "policy_source": "band.psd_policy",
                "verdict_type": "limit_upper",
            }
        },
    }
    payload["test_contracts"] = project_ruleset_test_contracts(
        payload.get("test_contracts") or {},
        tests_supported=collect_ruleset_test_types(payload),
    )
    return payload


def _load_custom_empty_template() -> Dict[str, Any]:
    payload = {
        "id": "NEW_RULESET",
        "version": "2026.02",
        "schema_version": 2,
        "regulation": "KC",
        "tech": "WLAN",
        "case_dimensions": {
            "base": ["test_type", "frequency_band", "channel"],
            "optional_axes": [],
            "dimensions": {
                "frequency_band": {
                    "type": "enum",
                    "source": "bands",
                    "maps_to": "band",
                    "values": [],
                },
                "channel": {
                    "type": "numeric",
                    "source": "channel_groups",
                    "maps_to": "channel",
                },
            },
        },
        "bands": {},
        "instrument_profiles": {},
        "instrument_profile_refs": {},
        "plan_modes": {
            "Quick": {"channel_policy": "REPRESENTATIVES_ONLY"},
            "Full": {"channel_policy": "ALL_CHANNELS"},
        },
        "voltage_policy": {
            "enabled": False,
            "mode": "PERCENT_OF_NOMINAL",
            "nominal_source": "preset.nominal_voltage_v",
            "apply_to": [],
            "settle_time_ms": 0,
            "fallback_policy": "WARN_AND_CONTINUE",
            "levels": [],
        },
        "data_rate_policy": {
            "enabled": False,
            "apply_to": [],
            "non_applicable_mode": "OMIT",
            "by_standard": {},
        },
        "test_labels": {},
        "test_contracts": {},
    }
    payload["test_contracts"] = project_ruleset_test_contracts(
        payload.get("test_contracts") or {},
        tests_supported=collect_ruleset_test_types(payload),
    )
    return payload


def _fallback_wlan_template() -> Dict[str, Any]:
    payload = _load_minimal_template()
    payload["id"] = "NEW_WLAN_RULESET"
    payload["bands"]["2.4G"]["standards"] = ["802.11b", "802.11g", "802.11n", "802.11ax"]
    payload["bands"]["2.4G"]["tests_supported"] = ["PSD", "OBW", "SP", "RX"]
    payload["bands"]["2.4G"]["channel_groups"]["DEFAULT"]["channels"] = [1, 6, 11]
    payload["bands"]["2.4G"]["channel_groups"]["DEFAULT"]["representatives"] = {"LOW": 1, "MID": 6, "HIGH": 11}
    payload["bands"]["5G"] = deepcopy(payload["bands"]["2.4G"])
    payload["bands"]["5G"]["standards"] = ["802.11a", "802.11n", "802.11ac", "802.11ax"]
    payload["bands"]["5G"]["channel_groups"] = {
        "UNII-1": {
            "channels": [36, 40, 44, 48],
            "dfs_required": False,
            "representatives": {"LOW": 36, "MID": 44, "HIGH": 48},
        }
    }
    payload["bands"]["6G"] = deepcopy(payload["bands"]["2.4G"])
    payload["bands"]["6G"]["psd_result_unit"] = "DBM_PER_MHZ"
    payload["bands"]["6G"]["psd_policy"]["result_unit"] = "DBM_PER_MHZ"
    payload["bands"]["6G"]["psd_policy"]["limit"]["value"] = 1.0
    payload["bands"]["6G"]["psd_policy"]["limit"]["unit"] = "DBM_PER_MHZ"
    payload["bands"]["6G"]["psd"]["limit_value"] = 1.0
    payload["bands"]["6G"]["psd"]["limit_unit"] = "DBM_PER_MHZ"
    payload["bands"]["6G"]["standards"] = ["802.11ax", "802.11be"]
    payload["bands"]["6G"]["channel_groups"] = {
        "UNII-5": {
            "channels": [5, 37, 93],
            "dfs_required": False,
            "representatives": {"LOW": 5, "MID": 37, "HIGH": 93},
        }
    }
    payload["data_rate_policy"] = {
        "enabled": True,
        "apply_to": ["PSD", "RX"],
        "non_applicable_mode": "OMIT",
        "by_standard": {
            "802.11b": ["1M", "2M", "5.5M", "11M"],
            "802.11g": ["6M", "12M", "24M", "54M"],
            "802.11a": ["6M", "12M", "24M", "54M"],
            "802.11n": ["MCS0", "MCS7"],
            "802.11ac": ["MCS0", "MCS9"],
            "802.11ax": ["MCS0", "MCS11"],
            "802.11be": ["MCS0", "MCS13"],
        },
    }
    payload["voltage_policy"] = {
        "enabled": True,
        "mode": "PERCENT_OF_NOMINAL",
        "nominal_source": "preset.nominal_voltage_v",
        "apply_to": ["PSD", "OBW", "SP"],
        "settle_time_ms": 500,
        "fallback_policy": "WARN_AND_CONTINUE",
        "levels": [
            {"name": "LOW", "label": "Low (-5%)", "percent_offset": -5},
            {"name": "NOMINAL", "label": "Nominal", "percent_offset": 0},
            {"name": "HIGH", "label": "High (+5%)", "percent_offset": 5},
        ],
    }
    payload["test_labels"].update({
        "OBW": "Occupied Bandwidth (OBW)",
        "SP": "Spurious",
        "RX": "Receiver",
    })
    payload["instrument_profiles"]["OBW_DEFAULT"] = {
        "rbw_hz": 10000,
        "vbw_hz": 30000,
        "detector": "PEAK",
        "trace_mode": "MAXHOLD",
    }
    payload["instrument_profiles"]["SP_DEFAULT"] = {
        "rbw_hz": 100000,
        "vbw_hz": 300000,
        "detector": "PEAK",
        "trace_mode": "MAXHOLD",
    }
    payload["instrument_profile_refs"].update({"OBW": "OBW_DEFAULT", "SP": "SP_DEFAULT", "RX": "SP_DEFAULT"})
    payload["test_contracts"] = project_ruleset_test_contracts(
        payload.get("test_contracts") or {},
        tests_supported=collect_ruleset_test_types(payload),
    )
    return payload
