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
)
from .models import InstrumentProfile, Preset, Recipe, RuleSet, TestCase
from .ruleset_models import BandInfo, ChannelGroup, normalize_voltage_policy

log = logging.getLogger(__name__)


def center_freq_mhz_from_channel_5g(ch: int) -> float:
    return 5000 + 5 * ch


def _coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def _resolve_voltage_axis(recipe_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    policy = normalize_voltage_policy(recipe_meta.get("voltage_policy") or {})
    nominal_voltage_v = _coerce_float(recipe_meta.get("nominal_voltage_v"))
    if not bool(policy.get("enabled")):
        return [{}]
    if nominal_voltage_v is None or nominal_voltage_v <= 0:
        return [{}]

    levels = list(policy.get("levels") or [])
    if not levels:
        return [{}]

    settle_time_ms = _coerce_int(policy.get("settle_time_ms"), 0)
    axes: List[Dict[str, Any]] = []
    for level in levels:
        row = dict(level or {})
        name = str(row.get("name", "")).strip().upper()
        if not name:
            continue
        percent_offset = _coerce_float(row.get("percent_offset"))
        percent_offset = 0.0 if percent_offset is None else float(percent_offset)
        target_voltage_v = round(nominal_voltage_v * (1.0 + (percent_offset / 100.0)), 6)
        axes.append(
            {
                "voltage_condition": name,
                "voltage_condition_label": str(row.get("label", name)).strip() or name,
                "nominal_voltage_v": nominal_voltage_v,
                "target_voltage_v": target_voltage_v,
                "voltage_percent_offset": percent_offset,
                "voltage_settle_time_ms": settle_time_ms,
            }
        )
    return axes or [{}]


def _voltage_key_suffix(axis: Dict[str, Any]) -> str:
    condition = str(axis.get("voltage_condition", "") or "").strip()
    if not condition:
        return ""
    target_voltage_v = _coerce_float(axis.get("target_voltage_v"))
    if target_voltage_v is None:
        return f"|VCOND:{condition}"
    return f"|VCOND:{condition}|TV:{target_voltage_v:.6f}"


def _merge_case_tags(recipe, ch: int, ip, extra_tags: Dict[str, Any] | None = None) -> Dict[str, Any]:
    tags = {
        "plan_mode": recipe.plan_mode,
        "preset": recipe.meta.get("preset_name", ""),
        "group": "",
        "measurement_profile_name": ip.name,
        "ruleset_id": recipe.meta.get("ruleset_id", ""),
        "device_class": recipe.meta.get("device_class", ""),
        "psd_result_unit": recipe.meta.get("psd_result_unit", ""),
        "psd_canonical_unit": recipe.meta.get("psd_canonical_unit", ""),
        "psd_method": recipe.meta.get("psd_method", ""),
        "psd_limit_value": recipe.meta.get("psd_limit_value"),
        "psd_limit_unit": recipe.meta.get("psd_limit_unit", ""),
        "psd_limit_label": recipe.meta.get("psd_limit_label", ""),
        "psd_canonical_limit_value": recipe.meta.get("psd_canonical_limit_value"),
        "psd_unit_policy_source": recipe.meta.get("psd_unit_policy_source", ""),
        "voltage_policy_enabled": bool(recipe.meta.get("voltage_policy_enabled")),
        "voltage_policy_active": bool(recipe.meta.get("voltage_policy_active")),
        "voltage_policy_status": recipe.meta.get("voltage_policy_status", ""),
        "nominal_voltage_v": recipe.meta.get("nominal_voltage_v"),
    }
    if extra_tags:
        tags.update(extra_tags)
    return tags


def _resolve_profile_name_for_test_type(
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
        or default_profile_for_test_type(test_type)
        or "PSD_DEFAULT"
    ).strip()
    return normalize_profile_name(profile_name)


def _pick_representatives_from_group(
    group: ChannelGroup,
    rep_override: Optional[Dict[str, Any]] = None,
) -> List[int]:
    """
    ChannelGroup의 representatives를 기반으로 LOW/MID/HIGH 대표 채널을 선택.
    rep_override가 있으면 representatives를 override한 뒤 선택.
    rep_override 예: {"mid": 120} 또는 {"MID": 120}
    """
    reps = dict(group.representatives or {})
    if rep_override:
        reps.update({str(k).upper(): int(v) for k, v in rep_override.items()})

    if reps:
        out: List[int] = []
        for k in ("LOW", "MID", "HIGH"):
            v = reps.get(k)
            if v is not None and v not in out:
                out.append(int(v))
        return out

    chs = sorted(group.channels or [])
    if not chs:
        return []
    low = chs[0]
    high = chs[-1]
    mid = chs[(len(chs) - 1) // 2]
    out: List[int] = []
    for x in (low, mid, high):
        if x not in out:
            out.append(int(x))
    return out


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
    return standards[0] if len(standards) == 1 else "MULTI"


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
    selector_fallback_tests: List[str] = []
    device_class = str(sel.get("device_class", "")).strip()
    nominal_voltage_v = _coerce_float(sel.get("nominal_voltage_v"))
    voltage_policy = normalize_voltage_policy(getattr(ruleset, "voltage_policy", {}) or {})
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
    psd_policy = resolve_psd_runtime_policy(
        preset_unit=sel.get("psd_result_unit"),
        band=band,
        device_class=device_class,
        ruleset=ruleset,
        ruleset_id=ruleset.id,
    )
    psd_unit_policy_source = "preset_override" if str(sel.get("psd_result_unit", "")).strip() else "ruleset_default"
    for t in test_types:
        prof_name = _resolve_profile_name_for_test_type(ip_map, shared_profile_name, t)
        effective_profile_map[t] = prof_name
        if shared_profile_name and not normalize_profile_name(ip_map.get(t) or ""):
            selector_fallback_tests.append(t)
        ip = ruleset.instrument_profiles.get(prof_name)
        if ip is None:
            ip_by_test[t] = InstrumentProfile(
                name=prof_name,
                settings={
                    "profile_name": prof_name,
                    "instrument_snapshot_source": "measurement_profile_reference",
                },
            )
        else:
            settings = dict(ip.settings or {})
            settings.setdefault("profile_name", prof_name)
            settings.setdefault("instrument_snapshot_source", "ruleset.instrument_profiles")
            ip_by_test[t] = InstrumentProfile(name=ip.name, settings=settings)

    meta = {
        **runtime_meta,
        "preset_name": preset.name,
        "ruleset_id": ruleset.id,
        "wlan_expansion": wlan,
        "measurement_profile_name": shared_profile_name,
        "measurement_profile_by_test": dict(ip_map),
        "effective_measurement_profile_by_test": dict(effective_profile_map),
        "device_class": device_class,
        "voltage_policy": voltage_policy,
        "voltage_policy_enabled": voltage_policy_enabled,
        "voltage_policy_active": voltage_policy_active,
        "voltage_policy_status": voltage_policy_status,
        "nominal_voltage_v": nominal_voltage_v,
        "psd_result_unit": psd_policy["result_unit"],
        "psd_canonical_unit": PSD_CANONICAL_UNIT,
        "psd_method": psd_policy["method"],
        "psd_limit_value": psd_policy["limit_value"],
        "psd_limit_unit": psd_policy["limit_unit"],
        "psd_limit_label": psd_policy["limit_label"],
        "psd_canonical_limit_value": psd_policy["canonical_limit_value"],
        "psd_unit_policy_source": psd_unit_policy_source,
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
            "build_recipe measurement profile selection | preset=%s shared_profile=%s per_test=%s effective=%s selector_fallback_tests=%s conflicts=%s psd_method=%s psd_unit=%s psd_limit=%s %s voltage_policy_enabled=%s voltage_policy_active=%s voltage_policy_status=%s nominal_voltage_v=%s",
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
            nominal_voltage_v,
        )
    else:
        log.info(
            "build_recipe measurement profile selection | preset=%s shared_profile=(empty) per_test=%s effective=%s psd_method=%s psd_unit=%s psd_limit=%s %s voltage_policy_enabled=%s voltage_policy_active=%s voltage_policy_status=%s nominal_voltage_v=%s",
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


def expand_recipe(ruleset: RuleSet, recipe: Recipe) -> Iterable[TestCase]:
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
    voltage_axes = _resolve_voltage_axis(dict(recipe.meta or {}))
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
                        for voltage_axis in voltage_axes:
                            voltage_tags = dict(voltage_axis or {})
                            key = (
                                f"{recipe.tech}|{recipe.regulation}|{recipe.band}|{standard}|{phy_mode}|"
                                f"{test}|CH{ch}|BW{bw}{_voltage_key_suffix(voltage_tags)}"
                            )
                            tags = _merge_case_tags(
                                recipe,
                                ch,
                                ip,
                                {
                                    "group": find_group(ch),
                                    "phy_mode": phy_mode,
                                    **voltage_tags,
                                },
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
            channels.extend(_pick_representatives_from_group(group_obj, rep_override))

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
                for voltage_axis in voltage_axes:
                    voltage_tags = dict(voltage_axis or {})
                    key = (
                        f"{recipe.tech}|{recipe.regulation}|{recipe.band}|{recipe.standard}|"
                        f"{test}|CH{ch}|BW{bw}{_voltage_key_suffix(voltage_tags)}"
                    )
                    tags = _merge_case_tags(
                        recipe,
                        ch,
                        ip,
                        {
                            "group": find_group(ch),
                            **voltage_tags,
                        },
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
