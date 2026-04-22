from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from domain.test_item_pool import (
    get_test_item_definition,
    is_selectable_test_item,
)
from domain.test_item_registry import normalize_test_id, normalize_test_id_list, was_test_id_aliased

PSD_ALLOWED_COMPARATORS = {"upper_limit", "lower_limit"}
AXIS_ALLOWED_TYPES = {"enum", "numeric", "computed", "string"}
AXIS_CORE_NAMES = {"frequency_band", "standard", "bandwidth", "channel", "data_rate", "voltage"}
POLICY_BACKED_AXIS_TO_POLICY = {
    "voltage": "voltage_policy",
    "data_rate": "data_rate_policy",
}


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
        name = normalize_test_id(item)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    # An explicit empty list means "no restriction" in the current ruleset/editor contract.
    return out, bool(out)


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


def _normalize_string_list(values: Any, *, uppercase: bool = False) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in (values or []):
        text = str(item or "").strip()
        if uppercase:
            text = text.upper()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on", "enabled"}


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
    comparator = str(
        explicit.get("comparator")
        or legacy_psd.get("comparator")
        or band.get("psd_comparator")
        or "upper_limit"
    ).strip() or "upper_limit"
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
    if comparator not in PSD_ALLOWED_COMPARATORS:
        comparator = "upper_limit"

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


def normalize_axis_definition(name: str, raw: Dict[str, Any] | None) -> Dict[str, Any]:
    axis_name = str(name or "").strip()
    data = dict(raw or {})
    axis_type = str(data.get("type", "enum")).strip().lower() or "enum"
    if axis_type not in AXIS_ALLOWED_TYPES:
        axis_type = "enum"
    source = str(data.get("source", "")).strip()
    maps_to = str(data.get("maps_to", "")).strip()
    apply_to, apply_to_defined = _normalize_apply_to(data.get("apply_to"))
    values = _normalize_string_list(data.get("values") or [], uppercase=False)
    return {
        **data,
        "name": axis_name,
        "type": axis_type,
        "source": source,
        "maps_to": maps_to,
        "values": values,
        "optional": _coerce_bool(data.get("optional", False), False),
        "apply_to": apply_to,
        "apply_to_defined": apply_to_defined,
        "non_applicable_mode": str(data.get("non_applicable_mode", "OMIT")).strip().upper() or "OMIT",
        "policy_ref": str(data.get("policy_ref", "")).strip(),
    }


def normalize_instrument_profile_refs(
    raw: Dict[str, Any] | None,
    *,
    test_contracts: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    data = dict(raw or {})
    out: Dict[str, str] = {}
    for key, value in data.items():
        name = normalize_test_id(key)
        ref = str(value or "").strip()
        if not name or not ref:
            continue
        out[name] = ref

    for _, contract in dict(test_contracts or {}).items():
        if not isinstance(contract, dict):
            continue
        apply_to = normalize_test_id(contract.get("apply_to_test_type"))
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
            "apply_to_test_type": normalize_test_id(contract.get("apply_to_test_type")),
            "canonical_test_id": normalize_test_id(contract.get("apply_to_test_type") or contract.get("id") or key),
        }
        for extra_key, extra_value in contract.items():
            if extra_key not in normalized:
                normalized[extra_key] = extra_value
        out[str(key)] = normalized
    return out


def _find_matching_contract(raw_contracts: Dict[str, Any], test_id: str) -> Dict[str, Any]:
    normalized_test_id = normalize_test_id(test_id)
    for key, value in dict(raw_contracts or {}).items():
        if not isinstance(value, dict):
            continue
        candidate_test_id = normalize_test_id(
            value.get("apply_to_test_type") or value.get("canonical_test_id") or value.get("id") or key
        )
        if candidate_test_id == normalized_test_id:
            return dict(value)
    return {}


def build_test_contract_projection(test_id: str, raw_contracts: Dict[str, Any] | None = None) -> Dict[str, Any]:
    canonical_test_id = normalize_test_id(test_id)
    pool_item = get_test_item_definition(canonical_test_id) or {}
    overlay = _find_matching_contract(raw_contracts or {}, canonical_test_id)
    display_name = str(pool_item.get("display_name") or canonical_test_id)
    default_profile_ref = str(
        overlay.get("default_profile_ref")
        or overlay.get("default_profile")
        or pool_item.get("default_profile_ref")
        or ""
    ).strip()
    measurement_class = str(
        overlay.get("measurement_class")
        or pool_item.get("measurement_class")
        or ""
    ).strip()
    required_instruments = [
        str(item).strip()
        for item in (overlay.get("required_instruments") or pool_item.get("required_instruments") or [])
        if str(item).strip()
    ]
    result_fields = [
        str(item).strip()
        for item in (overlay.get("result_fields") or pool_item.get("result_fields") or [])
        if str(item).strip()
    ]
    verdict_type = str(
        overlay.get("verdict_type")
        or pool_item.get("verdict_type")
        or "custom"
    ).strip()
    return {
        **overlay,
        "id": canonical_test_id,
        "name": display_name,
        "measurement_class": measurement_class,
        "required_instruments": required_instruments,
        "result_fields": result_fields,
        "verdict_type": verdict_type,
        "default_profile_ref": default_profile_ref,
        "default_profile": default_profile_ref,
        "unit": str(overlay.get("unit") or pool_item.get("unit") or "").strip(),
        "unit_source": "informational_only",
        "policy_source": str(overlay.get("policy_source") or f"pool:{canonical_test_id}").strip(),
        "editor_hint": str(overlay.get("editor_hint") or "pool_projection").strip(),
        "apply_to_test_type": canonical_test_id,
        "canonical_test_id": canonical_test_id,
        "pool_ref": canonical_test_id,
        "display_name": display_name,
        "procedure_key": str(pool_item.get("procedure_key") or "").strip(),
    }


def project_ruleset_test_contracts(
    raw_contracts: Dict[str, Any] | None,
    *,
    tests_supported: List[str] | None = None,
) -> Dict[str, Dict[str, Any]]:
    projected: Dict[str, Dict[str, Any]] = {}
    test_ids = normalize_test_id_list(tests_supported or [])
    if not test_ids:
        normalized_contracts = normalize_test_contracts(raw_contracts or {})
        test_ids = normalize_test_id_list(
            contract.get("apply_to_test_type")
            for contract in normalized_contracts.values()
            if isinstance(contract, dict)
        )
    for test_id in test_ids:
        projected[test_id] = build_test_contract_projection(test_id, raw_contracts)
    return projected


def normalize_case_dimensions(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    data = dict(raw or {})
    has_explicit_dimensions = bool(data)
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
    optional_axes = _ensure_policy_backed_optional_axes(optional_axes)
    dimensions_raw = dict(data.get("dimensions") or {})
    dimensions: Dict[str, Dict[str, Any]] = {}
    for name, item in dimensions_raw.items():
        if not isinstance(item, dict):
            continue
        axis_name = str(name or "").strip()
        if not axis_name:
            continue
        dimensions[axis_name] = normalize_axis_definition(axis_name, item)

    if not dimensions:
        dimensions = {
            "frequency_band": normalize_axis_definition("frequency_band", {
                "type": "enum",
                "source": "bands",
                "maps_to": "band",
            }),
            "standard": normalize_axis_definition("standard", {
                "type": "enum",
                "source": "preset.standard_or_wlan_expansion",
                "maps_to": "standard",
            }),
            "bandwidth": normalize_axis_definition("bandwidth", {
                "type": "numeric",
                "source": "preset.bandwidth_mhz",
                "maps_to": "bw_mhz",
            }),
            "channel": normalize_axis_definition("channel", {
                "type": "numeric",
                "source": "channel_groups",
                "maps_to": "channel",
            }),
            "data_rate": normalize_axis_definition("data_rate", {
                "type": "enum",
                "source": "data_rate_policy",
                "maps_to": "tags.data_rate",
                "optional": True,
                "policy_ref": "data_rate_policy",
                "non_applicable_mode": "OMIT",
            }),
            "voltage": normalize_axis_definition("voltage", {
                "type": "computed",
                "source": "voltage_policy",
                "maps_to": "tags.voltage_condition",
                "optional": True,
                "policy_ref": "voltage_policy",
                "non_applicable_mode": "OMIT",
            }),
        }
    return {
        "defined": has_explicit_dimensions,
        "base": base,
        "optional_axes": optional_axes,
        "dimensions": dimensions,
    }


def _ensure_policy_backed_optional_axes(optional_axes: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in (optional_axes or []):
        name = str((item or {}).get("name", "")).strip()
        policy_ref = str((item or {}).get("policy_ref", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if name in POLICY_BACKED_AXIS_TO_POLICY and not policy_ref:
            policy_ref = POLICY_BACKED_AXIS_TO_POLICY[name]
        normalized.append({"name": name, "policy_ref": policy_ref})
    for axis_name, policy_key in POLICY_BACKED_AXIS_TO_POLICY.items():
        if axis_name in seen:
            continue
        normalized.append({"name": axis_name, "policy_ref": policy_key})
        seen.add(axis_name)
    return normalized


def policy_backed_axis_policy_key(axis_name: str, axis_payload: Dict[str, Any] | None = None) -> str:
    axis = str(axis_name or "").strip()
    payload = dict(axis_payload or {})
    for candidate in (
        str(payload.get("policy_ref", "")).strip(),
        str(payload.get("source", "")).strip(),
        axis,
    ):
        if candidate in {"voltage", "voltage_policy"}:
            return "voltage_policy"
        if candidate in {"data_rate", "data_rate_policy"}:
            return "data_rate_policy"
    return ""


def effective_policy_backed_axis_apply_to(
    axis_name: str,
    axis_payload: Dict[str, Any] | None,
    *,
    voltage_policy: Dict[str, Any] | None,
    data_rate_policy: Dict[str, Any] | None,
) -> tuple[List[str], bool, str]:
    policy_key = policy_backed_axis_policy_key(axis_name, axis_payload)
    if policy_key == "voltage_policy":
        policy = normalize_voltage_policy(voltage_policy or {})
    elif policy_key == "data_rate_policy":
        policy = normalize_data_rate_policy(data_rate_policy or {})
    else:
        apply_to, apply_to_defined = _normalize_apply_to(dict(axis_payload or {}).get("apply_to"))
        return apply_to, apply_to_defined, f"case_dimensions.dimensions.{axis_name}.apply_to"

    if bool(policy.get("apply_to_defined")):
        return list(policy.get("apply_to") or []), True, f"{policy_key}.apply_to"

    apply_to, apply_to_defined = _normalize_apply_to(dict(axis_payload or {}).get("apply_to"))
    if apply_to_defined:
        return apply_to, True, f"case_dimensions.dimensions.{axis_name}.apply_to"
    return [], False, f"{policy_key}.apply_to"


def sync_policy_backed_axis_contracts(
    *,
    case_dimensions: Dict[str, Any] | None,
    voltage_policy: Dict[str, Any] | None,
    data_rate_policy: Dict[str, Any] | None,
) -> Dict[str, Dict[str, Any]]:
    synced_case_dimensions = normalize_case_dimensions(case_dimensions or {})
    synced_voltage_policy = normalize_voltage_policy(voltage_policy or {})
    synced_data_rate_policy = normalize_data_rate_policy(data_rate_policy or {})

    dimensions = dict(synced_case_dimensions.get("dimensions") or {})
    optional_axes = _ensure_policy_backed_optional_axes(list(synced_case_dimensions.get("optional_axes") or []))

    for axis_name, policy_key in POLICY_BACKED_AXIS_TO_POLICY.items():
        axis_payload = dict(dimensions.get(axis_name) or {})
        if policy_key == "voltage_policy":
            policy = dict(synced_voltage_policy)
        else:
            policy = dict(synced_data_rate_policy)

        axis_apply_to, axis_apply_to_defined = _normalize_apply_to(axis_payload.get("apply_to"))
        if not bool(policy.get("apply_to_defined")) and axis_apply_to_defined:
            policy["apply_to"] = list(axis_apply_to)
            if policy_key == "voltage_policy":
                synced_voltage_policy = normalize_voltage_policy(policy)
            else:
                synced_data_rate_policy = normalize_data_rate_policy(policy)

        if not axis_payload:
            continue

        axis_payload.setdefault("name", axis_name)
        axis_payload.setdefault("optional", True)
        if not str(axis_payload.get("policy_ref", "")).strip():
            axis_payload["policy_ref"] = policy_key
        if not str(axis_payload.get("source", "")).strip():
            axis_payload["source"] = policy_key

        if policy_key == "voltage_policy":
            effective_policy = synced_voltage_policy
        else:
            effective_policy = synced_data_rate_policy

        if bool(effective_policy.get("apply_to_defined")):
            axis_payload["apply_to"] = list(effective_policy.get("apply_to") or [])
        elif axis_apply_to_defined:
            axis_payload["apply_to"] = list(axis_apply_to)
        else:
            axis_payload["apply_to"] = []
        dimensions[axis_name] = normalize_axis_definition(axis_name, axis_payload)

    synced_case_dimensions["optional_axes"] = optional_axes
    synced_case_dimensions["dimensions"] = dimensions
    synced_case_dimensions = normalize_case_dimensions(synced_case_dimensions)

    return {
        "case_dimensions": synced_case_dimensions,
        "voltage_policy": synced_voltage_policy,
        "data_rate_policy": synced_data_rate_policy,
    }


def collect_ruleset_test_types(raw: Dict[str, Any] | None) -> List[str]:
    out: List[str] = []
    for _, band_payload in dict((raw or {}).get("bands") or {}).items():
        if not isinstance(band_payload, dict):
            continue
        for test_type in normalize_test_id_list(band_payload.get("tests_supported") or []):
            if test_type not in out:
                out.append(test_type)
    if out:
        return out
    contracts = normalize_test_contracts((raw or {}).get("test_contracts") or {})
    for contract_payload in contracts.values():
        test_type = normalize_test_id(contract_payload.get("apply_to_test_type"))
        if test_type and test_type not in out:
            out.append(test_type)
    return out


def validate_ruleset_payload(raw: Dict[str, Any] | None) -> Dict[str, List[Dict[str, str]]]:
    payload = dict(raw or {})
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    bands = dict(payload.get("bands") or {})
    registry_test_types = collect_ruleset_test_types(payload)
    ruleset_tech = str(payload.get("tech", "")).strip().upper()
    band_advertised_test_types: List[str] = []
    contract_test_types: List[str] = []
    projected_contracts = project_ruleset_test_contracts(
        payload.get("test_contracts") or {},
        tests_supported=registry_test_types,
    )
    instrument_profile_refs = normalize_instrument_profile_refs(
        payload.get("instrument_profile_refs") or {},
        test_contracts=projected_contracts,
    )
    instrument_profiles = dict(payload.get("instrument_profiles") or {})
    synced = sync_policy_backed_axis_contracts(
        case_dimensions=payload.get("case_dimensions") or {},
        voltage_policy=payload.get("voltage_policy") or {},
        data_rate_policy=payload.get("data_rate_policy") or {},
    )
    case_dimensions = synced["case_dimensions"]
    data_rate_policy = synced["data_rate_policy"]
    voltage_policy = synced["voltage_policy"]

    seen_band_names: set[str] = set()
    for band_name, band_payload in bands.items():
        canonical_band_name = str(band_name or "").strip().upper()
        if not canonical_band_name:
            errors.append({"path": "bands", "message": "Band name must not be empty."})
            continue
        if canonical_band_name in seen_band_names:
            errors.append({"path": f"bands.{band_name}", "message": "Duplicate band key detected (case-insensitive)."})
        seen_band_names.add(canonical_band_name)

        normalized_psd = normalize_psd_policy(band_payload if isinstance(band_payload, dict) else {})
        if not normalized_psd.get("method"):
            errors.append({"path": f"bands.{band_name}.psd_policy.method", "message": "PSD policy method is required."})
        if not normalized_psd.get("result_unit"):
            errors.append({"path": f"bands.{band_name}.psd_policy.result_unit", "message": "PSD policy result_unit is required."})
        if normalized_psd.get("limit", {}).get("value") in (None, ""):
            errors.append({"path": f"bands.{band_name}.psd_policy.limit.value", "message": "PSD policy limit value is required."})
        if not normalized_psd.get("limit", {}).get("unit"):
            errors.append({"path": f"bands.{band_name}.psd_policy.limit.unit", "message": "PSD policy limit unit is required."})
        if normalized_psd.get("legacy_fields_present", {}).get("psd") and not normalized_psd.get("legacy_fields_present", {}).get("psd_policy"):
            warnings.append({"path": f"bands.{band_name}.psd", "message": "Legacy PSD block is in use; add psd_policy to make the canonical source explicit."})

        supported_tests = normalize_test_id_list((band_payload or {}).get("tests_supported") or [])
        for raw_test in list((band_payload or {}).get("tests_supported") or []):
            if was_test_id_aliased(raw_test):
                warnings.append({
                    "path": f"bands.{band_name}.tests_supported",
                    "message": f"Alias test item '{raw_test}' should be replaced with canonical ID '{normalize_test_id(raw_test)}'.",
                })
        for test_type in supported_tests:
            if test_type not in band_advertised_test_types:
                band_advertised_test_types.append(test_type)
            pool_item = get_test_item_definition(test_type)
            if pool_item is None:
                errors.append({
                    "path": f"bands.{band_name}.tests_supported",
                    "message": f"Test '{test_type}' is not defined in the global test item pool.",
                })
                continue
            if not is_selectable_test_item(test_type, tech=ruleset_tech):
                errors.append({
                    "path": f"bands.{band_name}.tests_supported",
                    "message": f"Test '{test_type}' is not selectable for tech '{ruleset_tech or '(empty)'}'. Ensure enabled=true and procedure_key are present in the pool.",
                })
            supported_techs = [str(item).strip().upper() for item in (pool_item.get("supported_techs") or []) if str(item).strip()]
            if supported_techs and ruleset_tech and ruleset_tech not in supported_techs:
                errors.append({
                    "path": f"bands.{band_name}.tests_supported",
                    "message": f"Test '{test_type}' does not support ruleset tech '{ruleset_tech}'. Supported techs: {supported_techs}.",
                })
            if test_type not in instrument_profile_refs:
                warnings.append({
                    "path": f"instrument_profile_refs.{test_type}",
                    "message": f"No instrument_profile_refs entry for test '{test_type}'. Runtime default fallback will be used.",
                })

    for policy_name, policy_payload in (("voltage_policy", voltage_policy), ("data_rate_policy", data_rate_policy)):
        for raw_test in list((payload.get(policy_name) or {}).get("apply_to") or []):
            if was_test_id_aliased(raw_test):
                warnings.append({
                    "path": f"{policy_name}.apply_to",
                    "message": f"Alias test item '{raw_test}' should be replaced with canonical ID '{normalize_test_id(raw_test)}'.",
                })
        for test_type in list(policy_payload.get("apply_to") or []):
            pool_item = get_test_item_definition(test_type)
            if pool_item is None:
                errors.append({
                    "path": f"{policy_name}.apply_to",
                    "message": f"apply_to includes '{test_type}', but that test is not defined in the global test item pool.",
                })
                continue
            if ruleset_tech and not is_selectable_test_item(test_type, tech=ruleset_tech):
                warnings.append({
                    "path": f"{policy_name}.apply_to",
                    "message": f"apply_to includes '{test_type}', but it is not selectable for tech '{ruleset_tech}'.",
                })
            if test_type not in registry_test_types:
                warnings.append({
                    "path": f"{policy_name}.apply_to",
                    "message": f"apply_to includes '{test_type}', but that test is not enabled by any band tests_supported entry yet. The policy selection will be saved and becomes active when the test is enabled for at least one band.",
                })

    by_standard = dict(data_rate_policy.get("by_standard") or {})
    known_standards: set[str] = set()
    for band_payload in bands.values():
        if isinstance(band_payload, dict):
            known_standards.update(_normalize_string_list(band_payload.get("standards") or [], uppercase=False))
    for standard_name, rates in by_standard.items():
        if standard_name not in known_standards:
            warnings.append({
                "path": f"data_rate_policy.by_standard.{standard_name}",
                "message": "Standard has rate definitions but is not declared by any band.",
            })
        if not rates:
            warnings.append({
                "path": f"data_rate_policy.by_standard.{standard_name}",
                "message": "Standard has an empty rate list.",
            })

    for test_type, ref_name in instrument_profile_refs.items():
        if not ref_name:
            errors.append({
                "path": f"instrument_profile_refs.{test_type}",
                "message": "Instrument profile reference must not be empty.",
            })
        elif instrument_profiles and ref_name not in instrument_profiles:
            warnings.append({
                "path": f"instrument_profile_refs.{test_type}",
                "message": f"Reference '{ref_name}' is not present in ruleset.instrument_profiles fallback snapshot.",
            })

    dimensions = dict(case_dimensions.get("dimensions") or {})
    seen_axis_names: set[str] = set()
    for axis_name, axis_payload in dimensions.items():
        policy_key = policy_backed_axis_policy_key(axis_name, axis_payload)
        effective_apply_to, _effective_apply_to_defined, effective_apply_to_path = effective_policy_backed_axis_apply_to(
            axis_name,
            axis_payload,
            voltage_policy=voltage_policy,
            data_rate_policy=data_rate_policy,
        )
        key = str(axis_name or "").strip().lower()
        if key in seen_axis_names:
            errors.append({"path": f"case_dimensions.dimensions.{axis_name}", "message": "Duplicate axis name detected."})
        seen_axis_names.add(key)
        axis_type = str(axis_payload.get("type", "")).strip().lower()
        if axis_type not in AXIS_ALLOWED_TYPES:
            errors.append({"path": f"case_dimensions.dimensions.{axis_name}.type", "message": f"Unsupported axis type '{axis_type}'."})
        if axis_type == "enum" and not axis_payload.get("source") and not list(axis_payload.get("values") or []):
            errors.append({
                "path": f"case_dimensions.dimensions.{axis_name}",
                "message": "Enum axis must define either values or a source.",
            })
        raw_axis_payload = dict((payload.get("case_dimensions") or {}).get("dimensions", {}).get(axis_name) or {})
        if not policy_key:
            raw_apply_to_items = list(raw_axis_payload.get("apply_to") or [])
        elif effective_apply_to_path == f"case_dimensions.dimensions.{axis_name}.apply_to":
            raw_apply_to_items = list(raw_axis_payload.get("apply_to") or [])
        else:
            raw_apply_to_items = []
        for raw_test in raw_apply_to_items:
            if was_test_id_aliased(raw_test):
                warnings.append({
                    "path": effective_apply_to_path,
                    "message": f"Alias test item '{raw_test}' should be replaced with canonical ID '{normalize_test_id(raw_test)}'.",
                })
        for test_type in effective_apply_to:
            pool_item = get_test_item_definition(test_type)
            if pool_item is None:
                errors.append({
                    "path": effective_apply_to_path,
                    "message": f"Axis apply_to includes '{test_type}', but that test is not defined in the global test item pool.",
                })
                continue
            supported_axes = [str(item).strip() for item in (pool_item.get("supported_axes") or []) if str(item).strip()]
            if supported_axes and axis_name not in supported_axes:
                errors.append({
                    "path": effective_apply_to_path,
                    "message": f"Axis '{axis_name}' is not supported by test '{test_type}'. Supported axes: {supported_axes}.",
                })
            if test_type not in registry_test_types:
                errors.append({
                    "path": effective_apply_to_path,
                    "message": f"Axis apply_to includes '{test_type}', but that test is not enabled by any band tests_supported entry.",
                })

    base_axes = [str(name).strip() for name in (case_dimensions.get("base") or []) if str(name).strip()]
    for axis_name in base_axes:
        if axis_name not in dimensions and axis_name not in {"test_type", "band", "bw"}:
            warnings.append({
                "path": "case_dimensions.base",
                "message": f"Base axis '{axis_name}' is not declared in case_dimensions.dimensions.",
            })

    optional_axis_names = [str(item.get("name", "")).strip() for item in (case_dimensions.get("optional_axes") or []) if str(item.get("name", "")).strip()]
    if len(optional_axis_names) != len(set(optional_axis_names)):
        errors.append({"path": "case_dimensions.optional_axes", "message": "Duplicate optional axis names detected."})

    contracts = normalize_test_contracts(payload.get("test_contracts") or {})
    for contract_name, contract_payload in contracts.items():
        raw_contract = dict((payload.get("test_contracts") or {}).get(contract_name) or {})
        raw_apply_to_test_type = raw_contract.get("apply_to_test_type")
        apply_to_test_type = normalize_test_id(contract_payload.get("apply_to_test_type"))
        if apply_to_test_type and apply_to_test_type not in contract_test_types:
            contract_test_types.append(apply_to_test_type)
        if was_test_id_aliased(raw_apply_to_test_type):
            warnings.append({
                "path": f"test_contracts.{contract_name}.apply_to_test_type",
                "message": f"Alias test item '{raw_apply_to_test_type}' should be replaced with canonical ID '{apply_to_test_type}'.",
            })
        if not apply_to_test_type:
            warnings.append({
                "path": f"test_contracts.{contract_name}.apply_to_test_type",
                "message": "Legacy contract is missing apply_to_test_type. Pool projection will supply the canonical mapping at runtime.",
            })
        if str(contract_payload.get("unit_source", "")).strip() != "informational_only":
            warnings.append({
                "path": f"test_contracts.{contract_name}.unit_source",
                "message": "Contract units should be informational_only; PSD/measurement policy must remain the source of truth.",
            })

    for test_type, contract_payload in projected_contracts.items():
        if test_type not in contract_test_types:
            contract_test_types.append(test_type)
        if not str(contract_payload.get("procedure_key", "")).strip():
            errors.append({
                "path": f"test_contracts.{test_type}",
                "message": f"Projected contract for '{test_type}' has no procedure_key in the global pool, so it cannot be selected.",
            })

    for test_type in band_advertised_test_types:
        if contract_test_types and test_type not in contract_test_types:
            errors.append({
                "path": "bands",
                "message": f"Band advertises test '{test_type}', but no test_contracts registry entry declares it.",
            })
    for test_type in contract_test_types:
        if band_advertised_test_types and test_type not in band_advertised_test_types:
            warnings.append({
                "path": "test_contracts",
                "message": f"test_contracts declares '{test_type}', but no band tests_supported entry advertises it.",
            })

    if not voltage_policy.get("levels") and voltage_policy.get("enabled"):
        warnings.append({"path": "voltage_policy.levels", "message": "Voltage policy is enabled but no levels are defined."})

    selected_tests = normalize_test_id_list(registry_test_types)
    dimensions = dict(case_dimensions.get("dimensions") or {})
    for axis_name, axis_payload in dimensions.items():
        apply_to, _apply_to_defined, apply_to_path = effective_policy_backed_axis_apply_to(
            axis_name,
            axis_payload,
            voltage_policy=voltage_policy,
            data_rate_policy=data_rate_policy,
        )
        target_tests = apply_to or selected_tests
        for test_type in target_tests:
            pool_item = get_test_item_definition(test_type)
            if pool_item is None:
                continue
            supported_axes = [str(item).strip() for item in (pool_item.get("supported_axes") or []) if str(item).strip()]
            if supported_axes and axis_name not in supported_axes:
                warnings.append({
                    "path": apply_to_path,
                    "message": f"Axis '{axis_name}' may not apply to test '{test_type}'. Supported axes: {supported_axes}.",
                })

    return {"errors": errors, "warnings": warnings}


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
            tests_supported=normalize_test_id_list(tests_supported),
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

        projected_test_types = collect_ruleset_test_types(d)
        test_contracts = project_ruleset_test_contracts(
            d.get("test_contracts") or {},
            tests_supported=projected_test_types,
        )
        instrument_profile_refs = normalize_instrument_profile_refs(
            d.get("instrument_profile_refs") or {},
            test_contracts=test_contracts,
        )

        synced = sync_policy_backed_axis_contracts(
            case_dimensions=d.get("case_dimensions") or {},
            voltage_policy=d.get("voltage_policy") or {},
            data_rate_policy=d.get("data_rate_policy") or {},
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
            voltage_policy=synced["voltage_policy"],
            data_rate_policy=synced["data_rate_policy"],
            case_dimensions=synced["case_dimensions"],
        )
