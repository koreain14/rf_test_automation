from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from application.psd_unit_policy import PSD_CANONICAL_UNIT, resolve_psd_runtime_policy
from application.test_type_symbols import (
    DEFAULT_TEST_ORDER,
    default_profile_for_test_type,
    normalize_profile_name,
    normalize_test_type_list,
    normalize_test_type_map,
    normalize_test_type_symbol,
)
from .axis_resolvers import (
    AxisResolverContext,
    axis_core_field,
    center_freq_mhz_from_channel_5g,
    coerce_float,
    coerce_int,
    data_rate_key_suffix,
    find_group_for_state,
    normalize_rate_list,
    pick_representatives_from_group,
    resolve_axis_values,
    resolve_data_rate_axis_for_test,
    resolve_voltage_axis_for_test,
    voltage_key_suffix,
)
from .models import InstrumentProfile, Preset, Recipe, RuleSet, TestCase
from .ruleset_models import BandInfo, normalize_data_rate_policy, normalize_voltage_policy

log = logging.getLogger(__name__)


def _merge_case_tags(recipe, ch: int, ip, extra_tags: Dict[str, Any] | None = None) -> Dict[str, Any]:
    tags = {
        "plan_mode": recipe.plan_mode,
        "preset": recipe.meta.get("preset_name", ""),
        "group": "",
        "measurement_profile_name": ip.name,
        "measurement_profile_precedence": recipe.meta.get("measurement_profile_precedence", "measurement_profile_wins_over_instrument_snapshot"),
        "ruleset_id": recipe.meta.get("ruleset_id", ""),
        "device_class": recipe.meta.get("device_class", ""),
        "psd_result_unit": recipe.meta.get("psd_result_unit", ""),
        "psd_canonical_unit": recipe.meta.get("psd_canonical_unit", ""),
        "psd_method": recipe.meta.get("psd_method", ""),
        "psd_limit_value": recipe.meta.get("psd_limit_value"),
        "psd_limit_unit": recipe.meta.get("psd_limit_unit", ""),
        "psd_limit_label": recipe.meta.get("psd_limit_label", ""),
        "psd_comparator": recipe.meta.get("psd_comparator", ""),
        "psd_canonical_limit_value": recipe.meta.get("psd_canonical_limit_value"),
        "psd_unit_policy_source": recipe.meta.get("psd_unit_policy_source", ""),
        "psd_policy_source_of_truth": recipe.meta.get("psd_policy_source_of_truth", "band.psd_policy_or_legacy_fallback"),
        "voltage_policy_enabled": bool(recipe.meta.get("voltage_policy_enabled")),
        "voltage_policy_active": bool(recipe.meta.get("voltage_policy_active")),
        "voltage_policy_status": recipe.meta.get("voltage_policy_status", ""),
        "data_rate_policy_enabled": bool(recipe.meta.get("data_rate_policy_enabled")),
        "data_rate_policy_active": bool(recipe.meta.get("data_rate_policy_active")),
        "data_rate_policy_status": recipe.meta.get("data_rate_policy_status", ""),
        "nominal_voltage_v": recipe.meta.get("nominal_voltage_v"),
        "instrument_profiles_role": recipe.meta.get("instrument_profiles_role", "fallback_snapshot_only"),
    }
    if extra_tags:
        tags.update(extra_tags)
    return tags


def _resolve_profile_name_for_test_type(
    ruleset,
    ip_map: Dict[str, Any],
    shared_profile_name: str,
    test_type: str,
) -> str:
    """
    Resolve a profile name using one consistent contract:
    preset per-test override first, shared selector second, shared defaults last.
    """
    profile_name = str(
        ip_map.get(test_type)
        or shared_profile_name
        or dict(getattr(ruleset, "instrument_profile_refs", {}) or {}).get(test_type)
        or default_profile_for_test_type(test_type)
        or "PSD_DEFAULT"
    ).strip()
    return normalize_profile_name(profile_name)


def _extract_wlan_expansion(selection: Dict[str, Any]) -> Dict[str, Any]:
    wlan = dict(selection.get("wlan_expansion") or {})
    if wlan:
        return wlan
    meta = dict(selection.get("metadata") or {})
    return dict(meta.get("wlan_expansion") or {})


def _extract_runtime_meta(selection: Dict[str, Any]) -> Dict[str, Any]:
    meta = dict(selection.get("metadata") or {})
    # WLAN expansion is normalized separately into recipe.meta["wlan_expansion"].
    meta.pop("wlan_expansion", None)
    return meta


def _derive_standard_summary(wlan: Dict[str, Any]) -> str:
    standards: List[str] = []
    for item in (wlan.get("mode_plan") or []):
        standard = str(item.get("standard", item.get("mode", ""))).strip()
        if standard and standard not in standards:
            standards.append(standard)
    if not standards:
        return ""
    return standards[0] if len(standards) == 1 else ""


def _derive_bandwidth_summary(wlan: Dict[str, Any]) -> List[int]:
    out: List[int] = []
    for item in (wlan.get("channel_plan") or []):
        try:
            bw = int(item.get("bandwidth_mhz"))
        except Exception:
            continue
        if bw not in out:
            out.append(bw)
    if out:
        return out
    for item in (wlan.get("mode_plan") or []):
        for bw in (item.get("bandwidths_mhz") or []):
            try:
                value = int(bw)
            except Exception:
                continue
            if value not in out:
                out.append(value)
    return out


def _derive_channel_summary(wlan: Dict[str, Any]) -> Dict[str, Any]:
    all_channels: List[int] = []
    for item in (wlan.get("channel_plan") or []):
        for ch in (item.get("channels") or []):
            try:
                value = int(ch)
            except Exception:
                continue
            if value not in all_channels:
                all_channels.append(value)
    return {
        "policy": "CUSTOM_LIST",
        "channels": all_channels,
        "grouping": "",
        "groups": [],
        "representatives_override": {},
    }


def _normalize_case_dimensions_meta(recipe_meta: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(recipe_meta.get("case_dimensions") or {})
    dimensions = dict(raw.get("dimensions") or {})
    return {
        "defined": bool(raw.get("defined", False)),
        "base": [str(x).strip() for x in (raw.get("base") or []) if str(x).strip()],
        "optional_axes": list(raw.get("optional_axes") or []),
        "dimensions": {
            str(name).strip(): dict(value or {})
            for name, value in dimensions.items()
            if str(name).strip() and isinstance(value, dict)
        },
    }


def _ordered_axis_names(case_dimensions: Dict[str, Any]) -> List[str]:
    base = [str(name).strip() for name in (case_dimensions.get("base") or []) if str(name).strip()]
    dimensions = dict(case_dimensions.get("dimensions") or {})
    ordered: List[str] = []
    for axis_name in base:
        if axis_name not in ordered:
            ordered.append(axis_name)
    for axis_name in dimensions.keys():
        if axis_name not in ordered:
            ordered.append(axis_name)
    if "test_type" not in ordered:
        ordered.insert(0, "test_type")
    return ordered


def _initial_axis_state(case_dimensions: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "fields": {},
        "tags": {
            "axis_values": {},
            "axis_order": [str(name).strip() for name in (case_dimensions.get("base") or []) if str(name).strip()],
        },
        "key_suffix": "",
    }


def _apply_axis_payload_to_state(
    state: Dict[str, Any],
    *,
    axis_name: str,
    axis_def: Dict[str, Any],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    merged_fields = dict(state.get("fields") or {})
    merged_fields.update(dict(payload.get("fields") or {}))

    merged_tags = dict(state.get("tags") or {})
    axis_values = dict(merged_tags.get("axis_values") or {})
    axis_value = payload.get("axis_value")
    if axis_value is not None:
        axis_values[axis_name] = axis_value
    merged_tags["axis_values"] = axis_values

    axis_order = list(merged_tags.get("axis_order") or [])
    if axis_name not in axis_order:
        axis_order.append(axis_name)
    merged_tags["axis_order"] = axis_order
    merged_tags.update(dict(payload.get("tags") or {}))

    return {
        "fields": merged_fields,
        "tags": merged_tags,
        "key_suffix": f"{state.get('key_suffix', '')}{payload.get('key_suffix', '')}",
    }


def _expand_axis_product(ruleset: RuleSet, recipe: Recipe, case_dimensions: Dict[str, Any]) -> List[Dict[str, Any]]:
    recipe_meta = dict(recipe.meta or {})
    dimensions = dict(case_dimensions.get("dimensions") or {})
    states: List[Dict[str, Any]] = [_initial_axis_state(case_dimensions)]
    for axis_name in _ordered_axis_names(case_dimensions):
        axis_def = dict(dimensions.get(axis_name) or {"name": axis_name, "maps_to": axis_core_field(axis_name, {})})
        next_states: List[Dict[str, Any]] = []
        for state in states:
            payloads = resolve_axis_values(
                AxisResolverContext(
                    axis_name=axis_name,
                    axis_def=axis_def,
                    recipe=recipe,
                    ruleset=ruleset,
                    recipe_meta=recipe_meta,
                    state=state,
                )
            )
            if not payloads:
                next_states.append(state)
                continue
            log.info(
                "CASE AXIS: axis=%s test_type=%s payload_count=%s values=%s",
                axis_name,
                str(dict(state.get("fields") or {}).get("test_type", "") or ""),
                len(payloads),
                [payload.get("axis_value") for payload in payloads],
            )
            for payload in payloads:
                next_states.append(_apply_axis_payload_to_state(state, axis_name=axis_name, axis_def=axis_def, payload=payload))
        states = next_states or states
    return states


def _build_case_from_axis_combination(ruleset: RuleSet, recipe: Recipe, state: Dict[str, Any]) -> TestCase:
    fields = dict(state.get("fields") or {})
    test_type = normalize_test_type_symbol(fields.get("test_type", ""))
    ip = recipe.instrument_profile_by_test[test_type]
    channel = coerce_int(fields.get("channel"), 0)
    band = str(fields.get("band", recipe.band) or "")
    standard = str(fields.get("standard", recipe.standard) or "")
    bw_mhz = coerce_int(fields.get("bw_mhz"), 0)
    phy_mode = str(fields.get("phy_mode", "") or "")
    center_freq_mhz = coerce_float(fields.get("center_freq_mhz"))
    if center_freq_mhz is None:
        center_freq_mhz = center_freq_mhz_from_channel_5g(channel) if band == "5G" else 0.0

    tags = _merge_case_tags(
        recipe,
        channel,
        ip,
        {
            "group": find_group_for_state(ruleset, state),
            "phy_mode": phy_mode,
            "measurement_profile_ref_source": recipe.meta.get("effective_measurement_profile_ref_source_by_test", {}).get(test_type, ""),
            **dict(state.get("tags") or {}),
        },
    )

    if phy_mode:
        key_prefix = f"{recipe.tech}|{recipe.regulation}|{band}|{standard}|{phy_mode}|{test_type}|CH{channel}|BW{bw_mhz}"
    else:
        key_prefix = f"{recipe.tech}|{recipe.regulation}|{band}|{standard}|{test_type}|CH{channel}|BW{bw_mhz}"
    key = f"{key_prefix}{state.get('key_suffix', '')}"
    log.info(
        "CASE AXIS: standard=%s voltage=%s data_rate=%s bw=%s ch=%s test_type=%s axis_values=%s",
        standard,
        tags.get("voltage_condition", ""),
        tags.get("data_rate", ""),
        bw_mhz,
        channel,
        test_type,
        dict(tags.get("axis_values", {}) or {}),
    )

    return TestCase(
        test_type=test_type,
        band=band,
        standard=standard,
        channel=channel,
        center_freq_mhz=float(center_freq_mhz),
        bw_mhz=bw_mhz,
        instrument=dict(ip.settings),
        tags=tags,
        key=key,
    )


def build_recipe(ruleset: RuleSet, preset: Preset) -> Recipe:
    sel = dict(preset.selection or {})

    band = str(sel.get("band", "")).strip()
    plan_mode = str(sel.get("plan_mode", "Quick")).strip() or "Quick"
    test_types = normalize_test_type_list(sel.get("test_types") or [])
    shared_profile_name = normalize_profile_name(sel.get("measurement_profile_name") or "")

    wlan = _extract_wlan_expansion(sel)
    runtime_meta = _extract_runtime_meta(sel)
    standard = str(sel.get("standard", "")).strip()
    bw_list = [int(x) for x in (sel.get("bandwidth_mhz") or [])]
    channel_policy = dict(sel.get("channels") or {})

    if wlan:
        if not standard:
            standard = _derive_standard_summary(wlan)
        if not bw_list:
            bw_list = _derive_bandwidth_summary(wlan)
        if not channel_policy:
            channel_policy = _derive_channel_summary(wlan)

    ip_by_test: Dict[str, InstrumentProfile] = {}
    ip_map = normalize_test_type_map(sel.get("instrument_profile_by_test") or {})
    effective_profile_map: Dict[str, str] = {}
    effective_profile_ref_source: Dict[str, str] = {}
    selector_fallback_tests: List[str] = []
    device_class = str(sel.get("device_class", "")).strip()
    nominal_voltage_v = coerce_float(sel.get("nominal_voltage_v"))
    selected_data_rates = normalize_rate_list(sel.get("selected_data_rates") or [])
    voltage_policy = normalize_voltage_policy(getattr(ruleset, "voltage_policy", {}) or {})
    data_rate_policy = normalize_data_rate_policy(getattr(ruleset, "data_rate_policy", {}) or {})
    case_dimensions = dict(getattr(ruleset, "case_dimensions", {}) or {})
    voltage_policy_enabled = bool(voltage_policy.get("enabled"))
    voltage_levels = list(voltage_policy.get("levels") or [])
    voltage_policy_active = bool(voltage_policy_enabled and nominal_voltage_v and nominal_voltage_v > 0 and voltage_levels)
    voltage_policy_status = "disabled"
    if voltage_policy_active:
        voltage_policy_status = "enabled"
    elif voltage_policy_enabled and not voltage_levels:
        voltage_policy_status = "disabled_no_levels"
    elif voltage_policy_enabled and not nominal_voltage_v:
        voltage_policy_status = "disabled_missing_nominal"
    data_rate_policy_enabled = bool(data_rate_policy.get("enabled"))
    data_rate_policy_status = "enabled" if data_rate_policy_enabled else "disabled"
    psd_policy = resolve_psd_runtime_policy(
        preset_unit=sel.get("psd_result_unit"),
        band=band,
        device_class=device_class,
        ruleset=ruleset,
        ruleset_id=ruleset.id,
    )
    psd_unit_policy_source = "preset_override" if str(sel.get("psd_result_unit", "")).strip() else "ruleset_default"
    for t in test_types:
        prof_name = _resolve_profile_name_for_test_type(ruleset, ip_map, shared_profile_name, t)
        effective_profile_map[t] = prof_name
        if normalize_profile_name(ip_map.get(t) or ""):
            effective_profile_ref_source[t] = "preset.instrument_profile_by_test"
        elif shared_profile_name:
            effective_profile_ref_source[t] = "preset.measurement_profile_name"
        elif dict(getattr(ruleset, "instrument_profile_refs", {}) or {}).get(t):
            effective_profile_ref_source[t] = "ruleset.instrument_profile_refs"
        else:
            effective_profile_ref_source[t] = "default_profile_for_test_type"
        if shared_profile_name and not normalize_profile_name(ip_map.get(t) or ""):
            selector_fallback_tests.append(t)
        ip = ruleset.instrument_profiles.get(prof_name)
        if ip is None:
            ip_by_test[t] = InstrumentProfile(
                name=prof_name,
                settings={
                    "profile_name": prof_name,
                    "instrument_snapshot_source": "measurement_profile_reference",
                    "runtime_profile_precedence": "measurement_profile_wins_over_instrument_snapshot",
                },
            )
        else:
            settings = dict(ip.settings or {})
            settings.setdefault("profile_name", prof_name)
            settings.setdefault("instrument_snapshot_source", "ruleset.instrument_profiles")
            settings.setdefault("runtime_profile_precedence", "measurement_profile_wins_over_instrument_snapshot")
            ip_by_test[t] = InstrumentProfile(name=ip.name, settings=settings)

    meta = {
        **runtime_meta,
        "preset_name": preset.name,
        "ruleset_id": ruleset.id,
        "wlan_expansion": wlan,
        "measurement_profile_name": shared_profile_name,
        "measurement_profile_by_test": dict(ip_map),
        "effective_measurement_profile_by_test": dict(effective_profile_map),
        "effective_measurement_profile_ref_source_by_test": dict(effective_profile_ref_source),
        "instrument_profile_refs": dict(getattr(ruleset, "instrument_profile_refs", {}) or {}),
        "instrument_profiles_role": "fallback_snapshot_only",
        "case_dimensions": case_dimensions,
        "device_class": device_class,
        "voltage_policy": voltage_policy,
        "voltage_policy_enabled": voltage_policy_enabled,
        "voltage_policy_active": voltage_policy_active,
        "voltage_policy_status": voltage_policy_status,
        "voltage_policy_apply_to": list(voltage_policy.get("apply_to") or []),
        "voltage_policy_apply_to_defined": bool(voltage_policy.get("apply_to_defined")),
        "data_rate_policy": data_rate_policy,
        "data_rate_policy_enabled": data_rate_policy_enabled,
        "data_rate_policy_active": data_rate_policy_enabled,
        "data_rate_policy_status": data_rate_policy_status,
        "data_rate_policy_apply_to": list(data_rate_policy.get("apply_to") or []),
        "data_rate_policy_apply_to_defined": bool(data_rate_policy.get("apply_to_defined")),
        "selected_data_rates": list(selected_data_rates),
        "nominal_voltage_v": nominal_voltage_v,
        "psd_result_unit": psd_policy["result_unit"],
        "psd_canonical_unit": PSD_CANONICAL_UNIT,
        "psd_method": psd_policy["method"],
        "psd_limit_value": psd_policy["limit_value"],
        "psd_limit_unit": psd_policy["limit_unit"],
        "psd_limit_label": psd_policy["limit_label"],
        "psd_comparator": psd_policy["comparator"],
        "psd_canonical_limit_value": psd_policy["canonical_limit_value"],
        "psd_unit_policy_source": psd_unit_policy_source,
        "psd_policy_source_of_truth": "band.psd_policy_or_legacy_fallback",
        "measurement_profile_precedence": "measurement_profile_wins_over_instrument_snapshot",
    }
    pol = dict(sel.get("execution_policy") or {})
    if pol:
        pol["test_order"] = normalize_test_type_list(pol.get("test_order") or [])
        meta["execution_policy"] = pol
    else:
        meta["execution_policy"] = {
            "type": "CHANNEL_CENTRIC",
            "test_order": list(DEFAULT_TEST_ORDER),
            "include_bw_in_group": True,
        }

    if shared_profile_name:
        conflicts = sorted(
            f"{test_type}:{normalize_profile_name(profile_name)}"
            for test_type, profile_name in ip_map.items()
            if normalize_profile_name(profile_name) and normalize_profile_name(profile_name) != shared_profile_name
        )
        log.info(
            "build_recipe measurement profile selection | preset=%s shared_profile=%s per_test=%s effective=%s selector_fallback_tests=%s conflicts=%s psd_method=%s psd_unit=%s psd_limit=%s %s voltage_policy_enabled=%s voltage_policy_active=%s voltage_policy_status=%s voltage_policy_apply_to=%s data_rate_policy_enabled=%s data_rate_policy_apply_to=%s selected_data_rates=%s nominal_voltage_v=%s",
            preset.name,
            shared_profile_name,
            dict(ip_map),
            dict(effective_profile_map),
            selector_fallback_tests,
            conflicts,
            psd_policy["method"],
            psd_policy["result_unit"],
            psd_policy["limit_value"],
            psd_policy["limit_label"],
            voltage_policy_enabled,
            voltage_policy_active,
            voltage_policy_status,
            list(voltage_policy.get("apply_to") or []),
            data_rate_policy_enabled,
            list(data_rate_policy.get("apply_to") or []),
            list(selected_data_rates),
            nominal_voltage_v,
        )
    else:
        log.info(
            "build_recipe measurement profile selection | preset=%s shared_profile=(empty) per_test=%s effective=%s psd_method=%s psd_unit=%s psd_limit=%s %s voltage_policy_enabled=%s voltage_policy_active=%s voltage_policy_status=%s voltage_policy_apply_to=%s data_rate_policy_enabled=%s data_rate_policy_apply_to=%s selected_data_rates=%s nominal_voltage_v=%s",
            preset.name,
            dict(ip_map),
            dict(effective_profile_map),
            psd_policy["method"],
            psd_policy["result_unit"],
            psd_policy["limit_value"],
            psd_policy["limit_label"],
            voltage_policy_enabled,
            voltage_policy_active,
            voltage_policy_status,
            list(voltage_policy.get("apply_to") or []),
            data_rate_policy_enabled,
            list(data_rate_policy.get("apply_to") or []),
            list(selected_data_rates),
            nominal_voltage_v,
        )

    return Recipe(
        ruleset_id=ruleset.id,
        ruleset_version=ruleset.version,
        regulation=ruleset.regulation,
        tech=ruleset.tech,
        band=band,
        standard=standard,
        plan_mode=plan_mode,
        test_types=test_types,
        bandwidth_mhz=bw_list,
        channel_policy=channel_policy,
        instrument_profile_by_test=ip_by_test,
        meta=meta,
    )


def _expand_recipe_legacy(ruleset: RuleSet, recipe: Recipe) -> Iterable[TestCase]:
    if recipe.band not in ruleset.bands:
        raise ValueError(
            f"Band '{recipe.band}' not defined in ruleset '{ruleset.id}'. "
            f"Available: {list(ruleset.bands.keys())}"
        )

    band_info: BandInfo = ruleset.bands[recipe.band]

    def find_group(ch: int) -> str:
        for gname, group_obj in band_info.channel_groups.items():
            if ch in (group_obj.channels or []):
                return gname
        return ""

    wlan = dict(recipe.meta.get("wlan_expansion") or {})
    recipe_meta = dict(recipe.meta or {})
    voltage_axes_by_test: Dict[str, List[Dict[str, Any]]] = {}
    for test in recipe.test_types:
        axes = resolve_voltage_axis_for_test(recipe_meta, test)
        voltage_axes_by_test[test] = axes
        log.info(
            "expand_recipe voltage axis decision | ruleset_id=%s test_type=%s enabled=%s active=%s apply_to=%s apply_to_defined=%s applied=%s generated_levels=%s nominal_voltage_v=%s",
            recipe.meta.get("ruleset_id", ""),
            test,
            bool(recipe.meta.get("voltage_policy_enabled")),
            any(bool(axis.get("voltage_policy_active")) for axis in axes),
            recipe.meta.get("voltage_policy_apply_to", []),
            bool(recipe.meta.get("voltage_policy_apply_to_defined")),
            any(bool(axis.get("voltage_policy_applied")) for axis in axes),
            [str(axis.get("voltage_condition", "") or "") for axis in axes if axis.get("voltage_condition") not in (None, "")],
            recipe.meta.get("nominal_voltage_v"),
        )
    mode_plan = list(wlan.get("mode_plan") or [])
    channel_plan = list(wlan.get("channel_plan") or [])
    if mode_plan and channel_plan:
        for mode_item in mode_plan:
            standard = str(mode_item.get("standard", mode_item.get("mode", ""))).strip() or recipe.standard
            phy_mode = str(mode_item.get("phy_mode", "")).strip()
            bandwidths: List[int] = []
            for bw in (mode_item.get("bandwidths_mhz") or []):
                try:
                    bandwidths.append(int(bw))
                except Exception:
                    continue

            for bw in bandwidths:
                cp = next((item for item in channel_plan if int(item.get("bandwidth_mhz", -1)) == bw), None)
                if not cp:
                    continue
                channels = [int(x) for x in (cp.get("channels") or [])]
                freqs = [float(x) for x in (cp.get("frequencies_mhz") or [])]
                for idx, ch in enumerate(channels):
                    cf = freqs[idx] if idx < len(freqs) else (
                        center_freq_mhz_from_channel_5g(ch) if recipe.band == "5G" else 0.0
                    )
                    for test in recipe.test_types:
                        ip = recipe.instrument_profile_by_test[test]
                        data_rate_axes = resolve_data_rate_axis_for_test(recipe_meta, standard=standard, test_type=test)
                        log.info(
                            "expand_recipe data rate decision | ruleset_id=%s standard=%s test_type=%s enabled=%s active=%s apply_to=%s apply_to_defined=%s applied=%s chosen_data_rates=%s",
                            recipe.meta.get("ruleset_id", ""),
                            standard,
                            test,
                            bool(recipe.meta.get("data_rate_policy_enabled")),
                            any(bool(axis.get("data_rate_policy_active")) for axis in data_rate_axes),
                            recipe.meta.get("data_rate_policy_apply_to", []),
                            bool(recipe.meta.get("data_rate_policy_apply_to_defined")),
                            any(bool(axis.get("data_rate_policy_applied")) for axis in data_rate_axes),
                            [str(axis.get("data_rate", "") or "") for axis in data_rate_axes if axis.get("data_rate") not in (None, "")],
                        )
                        for data_rate_axis in data_rate_axes:
                            for voltage_axis in voltage_axes_by_test.get(test, [{}]):
                                voltage_tags = dict(voltage_axis or {})
                                data_rate_tags = dict(data_rate_axis or {})
                                key = (
                                    f"{recipe.tech}|{recipe.regulation}|{recipe.band}|{standard}|{phy_mode}|"
                                    f"{test}|CH{ch}|BW{bw}{data_rate_key_suffix(data_rate_tags)}{voltage_key_suffix(voltage_tags)}"
                                )
                                tags = _merge_case_tags(
                                    recipe,
                                    ch,
                                    ip,
                                    {
                                        "group": find_group(ch),
                                        "phy_mode": phy_mode,
                                        "measurement_profile_ref_source": recipe.meta.get("effective_measurement_profile_ref_source_by_test", {}).get(test, ""),
                                        **data_rate_tags,
                                        **voltage_tags,
                                    },
                                )
                                log.debug(
                                    "expand_recipe case generated | case_key=%s test_type=%s standard=%s data_rate=%s applied_rate=%s applied_voltage=%s condition=%s target_voltage_v=%s",
                                    key,
                                    test,
                                    standard,
                                    tags.get("data_rate", ""),
                                    bool(tags.get("data_rate_policy_applied")),
                                    bool(tags.get("voltage_policy_applied")),
                                    tags.get("voltage_condition", ""),
                                    tags.get("target_voltage_v"),
                                )
                                yield TestCase(
                                    test_type=test,
                                    band=recipe.band,
                                    standard=standard,
                                    channel=ch,
                                    center_freq_mhz=cf,
                                    bw_mhz=bw,
                                    instrument=dict(ip.settings),
                                    tags=tags,
                                    key=key,
                                )
        return

    pol = recipe.channel_policy
    policy = pol.get("policy")
    channels: List[int] = []

    if policy == "LOW_MID_HIGH_BY_GROUP":
        grouping = pol.get("grouping", "UNII")
        groups = pol.get("groups", [])
        reps_override_all = pol.get("representatives_override", {}) or {}

        if grouping != "UNII":
            raise ValueError(f"Unsupported grouping: {grouping}")

        cg = band_info.channel_groups
        for g in groups:
            if g not in cg:
                raise ValueError(
                    f"Channel group '{g}' not found in band '{band_info.name}'. "
                    f"Available: {list(cg.keys())}"
                )
            group_obj = cg[g]
            rep_override = reps_override_all.get(g, {}) or {}
            channels.extend(pick_representatives_from_group(group_obj, rep_override))

    elif policy == "ALL_CHANNELS":
        cg = band_info.channel_groups
        all_ch: List[int] = []
        for group_obj in cg.values():
            all_ch.extend([int(x) for x in (group_obj.channels or [])])
        channels = sorted(set(all_ch))

    elif policy == "CUSTOM_LIST":
        channels = [int(x) for x in pol.get("channels", [])]

    else:
        raise ValueError(f"Unsupported channel policy: {policy}")

    channels = sorted(set(channels))

    for test in recipe.test_types:
        ip = recipe.instrument_profile_by_test[test]
        for bw in recipe.bandwidth_mhz:
            for ch in channels:
                cf = center_freq_mhz_from_channel_5g(ch) if recipe.band == "5G" else 0.0
                data_rate_axes = resolve_data_rate_axis_for_test(recipe_meta, standard=recipe.standard, test_type=test)
                log.info(
                    "expand_recipe data rate decision | ruleset_id=%s standard=%s test_type=%s enabled=%s active=%s apply_to=%s apply_to_defined=%s applied=%s chosen_data_rates=%s",
                    recipe.meta.get("ruleset_id", ""),
                    recipe.standard,
                    test,
                    bool(recipe.meta.get("data_rate_policy_enabled")),
                    any(bool(axis.get("data_rate_policy_active")) for axis in data_rate_axes),
                    recipe.meta.get("data_rate_policy_apply_to", []),
                    bool(recipe.meta.get("data_rate_policy_apply_to_defined")),
                    any(bool(axis.get("data_rate_policy_applied")) for axis in data_rate_axes),
                    [str(axis.get("data_rate", "") or "") for axis in data_rate_axes if axis.get("data_rate") not in (None, "")],
                )
                for data_rate_axis in data_rate_axes:
                    for voltage_axis in voltage_axes_by_test.get(test, [{}]):
                        voltage_tags = dict(voltage_axis or {})
                        data_rate_tags = dict(data_rate_axis or {})
                        key = (
                            f"{recipe.tech}|{recipe.regulation}|{recipe.band}|{recipe.standard}|"
                            f"{test}|CH{ch}|BW{bw}{data_rate_key_suffix(data_rate_tags)}{voltage_key_suffix(voltage_tags)}"
                        )
                        tags = _merge_case_tags(
                            recipe,
                            ch,
                            ip,
                            {
                                "group": find_group(ch),
                                "measurement_profile_ref_source": recipe.meta.get("effective_measurement_profile_ref_source_by_test", {}).get(test, ""),
                                **data_rate_tags,
                                **voltage_tags,
                            },
                        )
                        log.debug(
                            "expand_recipe case generated | case_key=%s test_type=%s standard=%s data_rate=%s applied_rate=%s applied_voltage=%s condition=%s target_voltage_v=%s",
                            key,
                            test,
                            recipe.standard,
                            tags.get("data_rate", ""),
                            bool(tags.get("data_rate_policy_applied")),
                            bool(tags.get("voltage_policy_applied")),
                            tags.get("voltage_condition", ""),
                            tags.get("target_voltage_v"),
                        )
                        yield TestCase(
                            test_type=test,
                            band=recipe.band,
                            standard=recipe.standard,
                            channel=ch,
                            center_freq_mhz=cf,
                            bw_mhz=bw,
                            instrument=dict(ip.settings),
                            tags=tags,
                            key=key,
                        )


def _expand_recipe_by_axes(ruleset: RuleSet, recipe: Recipe) -> Iterable[TestCase]:
    recipe_meta = dict(recipe.meta or {})
    case_dimensions = _normalize_case_dimensions_meta(recipe_meta)
    if recipe.band and recipe.band not in ruleset.bands:
        raise ValueError(
            f"Band '{recipe.band}' not defined in ruleset '{ruleset.id}'. "
            f"Available: {list(ruleset.bands.keys())}"
        )

    for state in _expand_axis_product(ruleset, recipe, case_dimensions):
        yield _build_case_from_axis_combination(ruleset, recipe, state)


def expand_recipe(ruleset: RuleSet, recipe: Recipe) -> Iterable[TestCase]:
    case_dimensions = _normalize_case_dimensions_meta(dict(recipe.meta or {}))
    if bool(case_dimensions.get("defined")):
        yield from _expand_recipe_by_axes(ruleset, recipe)
        return
    yield from _expand_recipe_legacy(ruleset, recipe)
