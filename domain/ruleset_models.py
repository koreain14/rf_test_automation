from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _normalize_apply_to(raw: Any) -> tuple[List[str], bool]:
    if raw is None:
        return [], False
    if not isinstance(raw, list):
        return [], True

    out: List[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item or "").strip().upper()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out, True


def _normalize_psd_unit(value: Any) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "": "",
        "MW_PER_MHZ": "MW_PER_MHZ",
        "MW/MHZ": "MW_PER_MHZ",
        "DBM_PER_MHZ": "DBM_PER_MHZ",
        "DBM/MHZ": "DBM_PER_MHZ",
    }
    return aliases.get(text, text)


def _normalize_psd_method(value: Any) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "": "",
        "MARKER": "MARKER_PEAK",
        "PEAK": "MARKER_PEAK",
        "MARKER_PEAK": "MARKER_PEAK",
        "AVG": "AVERAGE",
        "AVERAGE": "AVERAGE",
        "TRACE_AVERAGE": "AVERAGE",
    }
    return aliases.get(text, text)


def normalize_psd_policy(raw_band: Dict[str, Any] | None) -> Dict[str, Any]:
    band = dict(raw_band or {})
    legacy_psd = dict(band.get("psd") or {})
    explicit = dict(band.get("psd_policy") or {})
    limit_block = dict(explicit.get("limit") or {})

    result_unit = _normalize_psd_unit(
        explicit.get("result_unit", band.get("psd_result_unit"))
    )
    method = _normalize_psd_method(
        explicit.get("method", legacy_psd.get("method", band.get("psd_method")))
    )
    comparator = str(explicit.get("comparator", "upper_limit") or "upper_limit").strip() or "upper_limit"
    raw_limit_value = (
        limit_block.get("value")
        if limit_block.get("value") not in (None, "")
        else explicit.get("limit_value", legacy_psd.get("limit_value", band.get("psd_limit_value")))
    )
    try:
        limit_value = float(raw_limit_value) if raw_limit_value not in (None, "") else None
    except Exception:
        limit_value = None
    limit_unit = _normalize_psd_unit(
        limit_block.get("unit")
        or explicit.get("limit_unit")
        or legacy_psd.get("limit_unit")
        or band.get("psd_limit_unit")
        or result_unit
    )

    return {
        "method": method,
        "result_unit": result_unit,
        "comparator": comparator,
        "limit": {
            "value": limit_value,
            "unit": limit_unit,
        },
        "legacy_fields_present": {
            "psd_result_unit": band.get("psd_result_unit") not in (None, ""),
            "psd": bool(legacy_psd),
            "psd_policy": bool(explicit),
        },
    }


def normalize_instrument_profile_refs(
    raw: Dict[str, Any] | None,
    *,
    test_contracts: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    data = dict(raw or {})
    out: Dict[str, str] = {}
    for key, value in data.items():
        name = str(key or "").strip().upper()
        ref = str(value or "").strip()
        if not name or not ref:
            continue
        out[name] = ref

    for _, contract in dict(test_contracts or {}).items():
        if not isinstance(contract, dict):
            continue
        apply_to = str(contract.get("apply_to_test_type") or "").strip().upper()
        ref = str(contract.get("default_profile_ref") or contract.get("default_profile") or "").strip()
        if apply_to and ref and apply_to not in out:
            out[apply_to] = ref
    return out


def normalize_test_contracts(raw: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in dict(raw or {}).items():
        if not isinstance(value, dict):
            continue
        contract = dict(value)
        default_profile_ref = str(contract.get("default_profile_ref") or contract.get("default_profile") or "").strip()
        normalized = {
            "id": str(contract.get("id", key)).strip() or str(key),
            "name": str(contract.get("name", key)).strip() or str(key),
            "measurement_class": str(contract.get("measurement_class", "")).strip(),
            "required_instruments": [str(x).strip() for x in (contract.get("required_instruments") or []) if str(x).strip()],
            "result_fields": [str(x).strip() for x in (contract.get("result_fields") or []) if str(x).strip()],
            "verdict_type": str(contract.get("verdict_type", "")).strip(),
            "default_profile_ref": default_profile_ref,
            "default_profile": str(contract.get("default_profile", "")).strip(),
            "unit": str(contract.get("unit", "")).strip(),
            "unit_source": str(contract.get("unit_source", "informational_only")).strip() or "informational_only",
            "policy_source": str(contract.get("policy_source", "")).strip(),
            "editor_hint": str(contract.get("editor_hint", "")).strip(),
            "apply_to_test_type": str(contract.get("apply_to_test_type", "")).strip().upper(),
        }
        for extra_key, extra_value in contract.items():
            if extra_key not in normalized:
                normalized[extra_key] = extra_value
        out[str(key)] = normalized
    return out


def normalize_case_dimensions(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    data = dict(raw or {})
    base = [str(x).strip() for x in (data.get("base") or []) if str(x).strip()]
    optional_axes: List[Dict[str, str]] = []
    for item in (data.get("optional_axes") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        policy_ref = str(item.get("policy_ref", "")).strip()
        if not name:
            continue
        optional_axes.append({"name": name, "policy_ref": policy_ref})
    if not base:
        base = ["test_type", "band", "standard", "bw", "channel"]
    if not optional_axes:
        optional_axes = [
            {"name": "voltage", "policy_ref": "voltage_policy"},
            {"name": "data_rate", "policy_ref": "data_rate_policy"},
        ]
    return {
        "base": base,
        "optional_axes": optional_axes,
    }


def normalize_voltage_policy(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    data = dict(raw or {})
    levels_raw = list(data.get("levels") or [])
    levels: List[Dict[str, Any]] = []
    for item in levels_raw:
        row = dict(item or {})
        name = str(row.get("name", "")).strip().upper()
        if not name:
            continue
        percent_offset = _coerce_float(
            row.get("percent_offset", row.get("offset_percent", row.get("percent")))
        )
        levels.append(
            {
                "name": name,
                "label": str(row.get("label", name)).strip() or name,
                "percent_offset": 0.0 if percent_offset is None else float(percent_offset),
            }
        )

    settle_time_ms = data.get("settle_time_ms", 0)
    try:
        settle_time_ms = int(settle_time_ms or 0)
    except Exception:
        settle_time_ms = 0
    if settle_time_ms < 0:
        settle_time_ms = 0

    apply_to, apply_to_defined = _normalize_apply_to(data.get("apply_to"))

    return {
        "enabled": bool(data.get("enabled", False)),
        "mode": str(data.get("mode", "PERCENT_OF_NOMINAL")).strip() or "PERCENT_OF_NOMINAL",
        "nominal_source": str(data.get("nominal_source", "preset.nominal_voltage_v")).strip() or "preset.nominal_voltage_v",
        "levels": levels,
        "apply_to": apply_to,
        "apply_to_defined": apply_to_defined,
        "settle_time_ms": settle_time_ms,
        "fallback_policy": str(data.get("fallback_policy", "WARN_AND_CONTINUE")).strip() or "WARN_AND_CONTINUE",
    }


def normalize_data_rate_policy(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    data = dict(raw or {})
    apply_to, apply_to_defined = _normalize_apply_to(data.get("apply_to"))

    by_standard_raw = dict(data.get("by_standard") or {})
    by_standard: Dict[str, List[str]] = {}
    for standard, rates_raw in by_standard_raw.items():
        standard_name = str(standard or "").strip()
        if not standard_name:
            continue
        rates: List[str] = []
        seen_rates: set[str] = set()
        for item in (rates_raw or []):
            rate_name = str(item or "").strip().upper()
            if not rate_name or rate_name in seen_rates:
                continue
            seen_rates.add(rate_name)
            rates.append(rate_name)
        by_standard[standard_name] = rates

    fallback_rate = str(data.get("fallback_rate", "") or "").strip().upper()
    non_applicable_mode = str(data.get("non_applicable_mode", "OMIT")).strip().upper() or "OMIT"

    return {
        "enabled": bool(data.get("enabled", False)),
        "apply_to": apply_to,
        "apply_to_defined": apply_to_defined,
        "by_standard": by_standard,
        "fallback_rate": fallback_rate,
        "non_applicable_mode": non_applicable_mode,
    }


@dataclass(frozen=True)
class ChannelGroup:
    name: str
    channels: List[int]
    dfs_required: bool
    representatives: Dict[str, int]  # {"LOW": 1, "MID": 6, "HIGH": 11}

    @staticmethod
    def from_dict(name: str, d: Dict[str, Any]) -> "ChannelGroup":
        if not isinstance(d, dict):
            raise TypeError(f"ChannelGroup '{name}' must be dict, got {type(d)}")

        channels = d.get("channels", [])
        if channels is None:
            channels = []
        if not isinstance(channels, list):
            raise TypeError(f"ChannelGroup '{name}'.channels must be list, got {type(channels)}")

        reps = d.get("representatives", {}) or {}
        if not isinstance(reps, dict):
            raise TypeError(f"ChannelGroup '{name}'.representatives must be dict, got {type(reps)}")

        channels_int = [int(x) for x in channels]
        reps_int = {str(k): int(v) for k, v in reps.items()}

        dfs_required = bool(d.get("dfs_required", False))

        return ChannelGroup(
            name=str(name),
            channels=channels_int,
            dfs_required=dfs_required,
            representatives=reps_int,
        )


@dataclass(frozen=True)
class BandInfo:
    band: str  # "2.4G" / "5G" / "6G"
    standards: List[str]
    tests_supported: List[str]
    channel_groups: Dict[str, ChannelGroup]
    device_classes: Optional[List[str]] = None
    psd_result_unit: Optional[str] = None
    psd_method: Optional[str] = None
    psd_limit_value: Optional[float] = None
    psd_limit_unit: Optional[str] = None
    psd: Optional[Dict[str, Any]] = None
    psd_policy: Optional[Dict[str, Any]] = None
    psd_by_device_class: Optional[Dict[str, Dict[str, Any]]] = None

    @staticmethod
    def from_dict(band: str, d: Dict[str, Any]) -> "BandInfo":
        if not isinstance(d, dict):
            raise TypeError(f"BandInfo '{band}' must be dict, got {type(d)}")

        standards = d.get("standards", []) or []
        if not isinstance(standards, list):
            raise TypeError(f"BandInfo '{band}'.standards must be list, got {type(standards)}")

        tests_supported = d.get("tests_supported", []) or []
        if not isinstance(tests_supported, list):
            raise TypeError(f"BandInfo '{band}'.tests_supported must be list, got {type(tests_supported)}")

        device_classes = d.get("device_classes", None)
        if device_classes is not None and not isinstance(device_classes, list):
            raise TypeError(f"BandInfo '{band}'.device_classes must be list or None, got {type(device_classes)}")

        cg_raw = d.get("channel_groups", {}) or {}
        if not isinstance(cg_raw, dict):
            raise TypeError(f"BandInfo '{band}'.channel_groups must be dict, got {type(cg_raw)}")

        channel_groups: Dict[str, ChannelGroup] = {
            str(name): ChannelGroup.from_dict(str(name), cg_dict)
            for name, cg_dict in cg_raw.items()
        }

        psd_raw = d.get("psd", {}) or {}
        if not isinstance(psd_raw, dict):
            raise TypeError(f"BandInfo '{band}'.psd must be dict, got {type(psd_raw)}")
        psd_policy = normalize_psd_policy(d)

        psd_by_device_class_raw = d.get("psd_by_device_class", {}) or {}
        if not isinstance(psd_by_device_class_raw, dict):
            raise TypeError(
                f"BandInfo '{band}'.psd_by_device_class must be dict, got {type(psd_by_device_class_raw)}"
            )

        psd_by_device_class = {
            str(name): dict(value or {})
            for name, value in psd_by_device_class_raw.items()
            if isinstance(value, dict)
        }

        raw_limit_value = psd_raw.get("limit_value", d.get("psd_limit_value"))
        try:
            limit_value = float(raw_limit_value) if raw_limit_value not in (None, "") else None
        except Exception:
            limit_value = None

        return BandInfo(
            band=str(band),
            standards=[str(x) for x in standards],
            tests_supported=[str(x) for x in tests_supported],
            channel_groups=channel_groups,
            device_classes=[str(x) for x in device_classes] if device_classes is not None else None,
            psd_result_unit=psd_policy.get("result_unit") or None,
            psd_method=psd_policy.get("method") or None,
            psd_limit_value=psd_policy.get("limit", {}).get("value", limit_value),
            psd_limit_unit=psd_policy.get("limit", {}).get("unit") or None,
            psd=dict(psd_raw),
            psd_policy=dict(psd_policy),
            psd_by_device_class=psd_by_device_class,
        )


@dataclass(frozen=True)
class InstrumentProfile:
    rbw_hz: int
    vbw_hz: int
    detector: str
    trace_mode: str

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "InstrumentProfile":
        if not isinstance(d, dict):
            raise TypeError(f"InstrumentProfile must be dict, got {type(d)}")

        return InstrumentProfile(
            rbw_hz=int(d.get("rbw_hz", 0)),
            vbw_hz=int(d.get("vbw_hz", 0)),
            detector=str(d.get("detector", "")),
            trace_mode=str(d.get("trace_mode", "")),
        )


@dataclass(frozen=True)
class PlanMode:
    name: str
    channel_policy: str

    @staticmethod
    def from_dict(name: str, d: Dict[str, Any]) -> "PlanMode":
        if not isinstance(d, dict):
            raise TypeError(f"PlanMode '{name}' must be dict, got {type(d)}")
        return PlanMode(
            name=str(name),
            channel_policy=str(d.get("channel_policy", "")),
        )


@dataclass(frozen=True)
class RuleSet:
    id: str
    version: str
    schema_version: int
    regulation: str
    tech: str
    bands: Dict[str, BandInfo]
    instrument_profiles: Dict[str, InstrumentProfile]
    instrument_profile_refs: Dict[str, str]
    plan_modes: Dict[str, PlanMode]
    test_contracts: Dict[str, Dict[str, Any]]
    voltage_policy: Dict[str, Any]
    data_rate_policy: Dict[str, Any]
    case_dimensions: Dict[str, Any]

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RuleSet":
        if not isinstance(d, dict):
            raise TypeError(f"RuleSet must be dict, got {type(d)}")

        rs_id = str(d.get("id", "")).strip()
        if not rs_id:
            raise KeyError("RuleSet.from_dict: missing 'id'")

        bands_raw = d.get("bands", {}) or {}
        if not isinstance(bands_raw, dict):
            raise TypeError(f"RuleSet.bands must be dict, got {type(bands_raw)}")

        bands: Dict[str, BandInfo] = {
            str(band): BandInfo.from_dict(str(band), band_dict)
            for band, band_dict in bands_raw.items()
        }

        ip_raw = d.get("instrument_profiles", {}) or {}
        if not isinstance(ip_raw, dict):
            raise TypeError(f"RuleSet.instrument_profiles must be dict, got {type(ip_raw)}")
        instrument_profiles = {
            str(k): InstrumentProfile.from_dict(v) for k, v in ip_raw.items()
        }

        pm_raw = d.get("plan_modes", {}) or {}
        if not isinstance(pm_raw, dict):
            raise TypeError(f"RuleSet.plan_modes must be dict, got {type(pm_raw)}")
        plan_modes = {str(k): PlanMode.from_dict(v) for k, v in pm_raw.items()}

        test_contracts = normalize_test_contracts(d.get("test_contracts") or {})
        instrument_profile_refs = normalize_instrument_profile_refs(
            d.get("instrument_profile_refs") or {},
            test_contracts=test_contracts,
        )

        return RuleSet(
            id=rs_id,
            version=str(d.get("version", "")).strip(),
            schema_version=int(d.get("schema_version", 1) or 1),
            regulation=str(d.get("regulation", "")).strip(),
            tech=str(d.get("tech", "")).strip(),
            bands=bands,
            instrument_profiles=instrument_profiles,
            instrument_profile_refs=instrument_profile_refs,
            plan_modes=plan_modes,
            test_contracts=test_contracts,
            voltage_policy=normalize_voltage_policy(d.get("voltage_policy") or {}),
            data_rate_policy=normalize_data_rate_policy(d.get("data_rate_policy") or {}),
            case_dimensions=normalize_case_dimensions(d.get("case_dimensions") or {}),
        )
