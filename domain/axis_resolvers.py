from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Protocol

from application.test_type_symbols import normalize_test_type_symbol

from .models import Recipe, RuleSet
from .ruleset_models import BandInfo, ChannelGroup, normalize_data_rate_policy, normalize_voltage_policy


AxisPayload = Dict[str, Any]
AxisState = Dict[str, Any]


class AxisResolver(Protocol):
    def __call__(self, context: "AxisResolverContext") -> List[AxisPayload]:
        ...


@dataclass(frozen=True)
class AxisResolverContext:
    axis_name: str
    axis_def: Dict[str, Any]
    recipe: Recipe
    ruleset: RuleSet
    recipe_meta: Dict[str, Any]
    state: AxisState


_RESOLVERS_BY_NAME: Dict[str, AxisResolver] = {}
_RESOLVERS_BY_SOURCE: Dict[str, AxisResolver] = {}
_RESOLVERS_BY_TYPE: Dict[str, AxisResolver] = {}


def register_axis_resolver(*, key: str, resolver: AxisResolver, kind: str = "name") -> None:
    normalized_kind = str(kind or "name").strip().lower()
    normalized_key = str(key or "").strip()
    if not normalized_key:
        return
    if normalized_kind == "source":
        _RESOLVERS_BY_SOURCE[normalized_key] = resolver
        return
    if normalized_kind == "type":
        _RESOLVERS_BY_TYPE[normalized_key] = resolver
        return
    _RESOLVERS_BY_NAME[normalized_key] = resolver


def get_axis_resolver(axis_name: str, axis_def: Dict[str, Any]) -> AxisResolver:
    source = str(axis_def.get("source", "") or "").strip()
    policy_ref = str(axis_def.get("policy_ref", "") or "").strip()
    axis_type = str(axis_def.get("type", "enum") or "enum").strip().lower()
    if source in _RESOLVERS_BY_SOURCE:
        return _RESOLVERS_BY_SOURCE[source]
    if policy_ref in _RESOLVERS_BY_SOURCE:
        return _RESOLVERS_BY_SOURCE[policy_ref]
    if axis_name in _RESOLVERS_BY_NAME:
        return _RESOLVERS_BY_NAME[axis_name]
    return _RESOLVERS_BY_TYPE.get(axis_type, _resolve_static_axis)


def resolve_axis_values(context: AxisResolverContext) -> List[AxisPayload]:
    current_test_type = str(dict(context.state.get("fields") or {}).get("test_type", "") or "")
    axis_gate_applies = not _policy_apply_to_overrides_axis(context)
    if current_test_type and axis_gate_applies and not axis_applies_to_test(context.axis_def, current_test_type):
        mode = axis_effective_non_applicable_mode(context.axis_name, context.axis_def)
        if mode == "OMIT":
            return []
        return [empty_axis_payload(context.axis_name, context.axis_def, status="not_applicable_test_type", include_empty_value=(mode == "EMPTY_VALUE"))]

    resolver = get_axis_resolver(context.axis_name, context.axis_def)
    payloads = list(resolver(context) or [])
    if payloads:
        return payloads

    mode = axis_effective_non_applicable_mode(context.axis_name, context.axis_def)
    if mode == "OMIT":
        return []
    return [empty_axis_payload(context.axis_name, context.axis_def, status="unresolved", include_empty_value=(mode == "EMPTY_VALUE"))]


def center_freq_mhz_from_channel_5g(ch: int) -> float:
    return 5000 + 5 * ch


def coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def normalize_rate_list(values: Any) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in (values or []):
        name = str(item or "").strip().upper()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def normalize_apply_to(values: Any) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in (values or []):
        name = normalize_test_type_symbol(item)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def apply_to_is_restricted(values: Any, apply_to_defined: Any = False) -> tuple[List[str], bool]:
    normalized = normalize_apply_to(values)
    # Empty apply_to must behave as unrestricted even if older payloads persisted
    # apply_to_defined=true with an empty list.
    return normalized, bool(normalized)


def _policy_key_for_axis(axis_name: str, axis_def: Dict[str, Any]) -> str:
    source = str(axis_def.get("source", "") or "").strip()
    policy_ref = str(axis_def.get("policy_ref", "") or "").strip()
    for candidate in (policy_ref, source, str(axis_name or "").strip()):
        if candidate in {"voltage_policy", "voltage"}:
            return "voltage_policy"
        if candidate in {"data_rate_policy", "data_rate"}:
            return "data_rate_policy"
    return ""


def _policy_apply_to_overrides_axis(context: "AxisResolverContext") -> bool:
    policy_key = _policy_key_for_axis(context.axis_name, context.axis_def)
    return bool(policy_key)


def axis_applies_to_test(axis_def: Dict[str, Any], test_type: str) -> bool:
    apply_to, apply_to_defined = apply_to_is_restricted(
        axis_def.get("apply_to"),
        axis_def.get("apply_to_defined"),
    )
    current_test_type = normalize_test_type_symbol(test_type)
    return (not apply_to_defined) or (current_test_type in apply_to)


def axis_core_field(axis_name: str, axis_def: Dict[str, Any]) -> str:
    maps_to = str(axis_def.get("maps_to", "") or "").strip()
    if maps_to and not maps_to.startswith("tags."):
        return maps_to
    aliases = {
        "frequency_band": "band",
        "band": "band",
        "bandwidth": "bw_mhz",
        "bw": "bw_mhz",
        "channel": "channel",
        "standard": "standard",
        "test_type": "test_type",
    }
    return aliases.get(str(axis_name or "").strip(), "")


def axis_effective_non_applicable_mode(axis_name: str, axis_def: Dict[str, Any]) -> str:
    mode = str(axis_def.get("non_applicable_mode", "OMIT") or "OMIT").strip().upper()
    source = str(axis_def.get("source", "") or "").strip()
    policy_ref = str(axis_def.get("policy_ref", "") or "").strip()
    if mode == "OMIT" and source in {"data_rate_policy", "voltage_policy"}:
        return "EMPTY_VALUE"
    if mode == "OMIT" and policy_ref in {"data_rate_policy", "voltage_policy"}:
        return "EMPTY_VALUE"
    return mode


def empty_axis_payload(axis_name: str, axis_def: Dict[str, Any], *, status: str, include_empty_value: bool) -> AxisPayload:
    return {
        "axis_value": "" if include_empty_value else None,
        "fields": {},
        "tags": {
            f"{axis_name}_axis_applied": False,
            f"{axis_name}_axis_status": status,
            f"{axis_name}_axis_non_applicable_mode": axis_effective_non_applicable_mode(axis_name, axis_def),
        },
        "key_suffix": "",
    }


def coerce_axis_scalar(axis_type: str, value: Any) -> Any:
    if axis_type == "numeric":
        ivalue = coerce_int(value, default=0)
        return ivalue if value not in (None, "") else ""
    return str(value or "").strip()


def generic_axis_key_suffix(axis_name: str, axis_value: Any) -> str:
    name = str(axis_name or "").strip().upper()
    value = str(axis_value if axis_value is not None else "").strip()
    if not name or not value:
        return ""
    return f"|AXIS:{name}={value}"


def data_rate_key_suffix(axis: Dict[str, Any]) -> str:
    data_rate = str(axis.get("data_rate", "") or "").strip()
    if not data_rate:
        return ""
    return f"|RATE:{data_rate}"


def voltage_key_suffix(axis: Dict[str, Any]) -> str:
    condition = str(axis.get("voltage_condition", "") or "").strip()
    if not condition:
        return ""
    target_voltage_v = coerce_float(axis.get("target_voltage_v"))
    if target_voltage_v is None:
        return f"|VCOND:{condition}"
    return f"|VCOND:{condition}|TV:{target_voltage_v:.6f}"


def build_mapped_axis_payload(axis_name: str, axis_def: Dict[str, Any], axis_value: Any, *, key_suffix: str = "") -> AxisPayload:
    maps_to = str(axis_def.get("maps_to", "") or "").strip()
    fields: Dict[str, Any] = {}
    tags: Dict[str, Any] = {
        f"{axis_name}_axis_applied": True,
        f"{axis_name}_axis_status": "enabled",
    }
    if maps_to.startswith("tags."):
        tags[maps_to.split(".", 1)[1]] = axis_value
    else:
        field_name = axis_core_field(axis_name, axis_def)
        if field_name:
            fields[field_name] = axis_value
        elif axis_value not in (None, ""):
            tags[axis_name] = axis_value
    return {
        "axis_value": axis_value,
        "fields": fields,
        "tags": tags,
        "key_suffix": key_suffix,
    }


def band_info_for_state(ruleset: RuleSet, state: AxisState) -> BandInfo | None:
    fields = dict(state.get("fields") or {})
    band = str(fields.get("band", "") or "").strip()
    if not band:
        return None
    return dict(getattr(ruleset, "bands", {}) or {}).get(band)


def find_group_for_state(ruleset: RuleSet, state: AxisState) -> str:
    band_info = band_info_for_state(ruleset, state)
    if band_info is None:
        return ""
    channel = coerce_int(dict(state.get("fields") or {}).get("channel"), 0)
    for gname, group_obj in band_info.channel_groups.items():
        if channel in (group_obj.channels or []):
            return gname
    return ""


def pick_representatives_from_group(group: ChannelGroup, rep_override: Dict[str, Any] | None = None) -> List[int]:
    reps = dict(group.representatives or {})
    if rep_override:
        reps.update({str(k).upper(): int(v) for k, v in rep_override.items()})

    if reps:
        out: List[int] = []
        for key in ("LOW", "MID", "HIGH"):
            value = reps.get(key)
            if value is not None and value not in out:
                out.append(int(value))
        return out

    channels = sorted(group.channels or [])
    if not channels:
        return []
    low = channels[0]
    high = channels[-1]
    mid = channels[(len(channels) - 1) // 2]
    out: List[int] = []
    for value in (low, mid, high):
        if value not in out:
            out.append(int(value))
    return out


def resolve_voltage_axis(recipe_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    policy = normalize_voltage_policy(recipe_meta.get("voltage_policy") or {})
    nominal_voltage_v = coerce_float(recipe_meta.get("nominal_voltage_v"))
    if not bool(policy.get("enabled")):
        return [{}]
    if nominal_voltage_v is None or nominal_voltage_v <= 0:
        return [{}]

    levels = list(policy.get("levels") or [])
    if not levels:
        return [{}]

    settle_time_ms = coerce_int(policy.get("settle_time_ms"), 0)
    axes: List[Dict[str, Any]] = []
    for level in levels:
        row = dict(level or {})
        name = str(row.get("name", "")).strip().upper()
        if not name:
            continue
        percent_offset = coerce_float(row.get("percent_offset"))
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


def resolve_voltage_axis_for_test(recipe_meta: Dict[str, Any], test_type: str) -> List[Dict[str, Any]]:
    policy = normalize_voltage_policy(recipe_meta.get("voltage_policy") or {})
    enabled = bool(policy.get("enabled"))
    nominal_voltage_v = coerce_float(recipe_meta.get("nominal_voltage_v"))
    levels = list(policy.get("levels") or [])
    apply_to, apply_to_defined = apply_to_is_restricted(
        policy.get("apply_to"),
        policy.get("apply_to_defined"),
    )
    current_test_type = normalize_test_type_symbol(test_type)
    applies = (not apply_to_defined) or (current_test_type in apply_to)

    if not enabled:
        return [{
            "voltage_policy_enabled": False,
            "voltage_policy_active": False,
            "voltage_policy_applied": False,
            "voltage_policy_status": "disabled",
            "voltage_policy_apply_to": list(apply_to),
            "voltage_policy_apply_to_defined": apply_to_defined,
        }]
    if not applies:
        return [{
            "voltage_policy_enabled": True,
            "voltage_policy_active": False,
            "voltage_policy_applied": False,
            "voltage_policy_status": "not_applicable_test_type",
            "voltage_policy_apply_to": list(apply_to),
            "voltage_policy_apply_to_defined": apply_to_defined,
        }]
    if nominal_voltage_v is None or nominal_voltage_v <= 0:
        return [{
            "voltage_policy_enabled": True,
            "voltage_policy_active": False,
            "voltage_policy_applied": False,
            "voltage_policy_status": "disabled_missing_nominal",
            "voltage_policy_apply_to": list(apply_to),
            "voltage_policy_apply_to_defined": apply_to_defined,
        }]
    if not levels:
        return [{
            "voltage_policy_enabled": True,
            "voltage_policy_active": False,
            "voltage_policy_applied": False,
            "voltage_policy_status": "disabled_no_levels",
            "voltage_policy_apply_to": list(apply_to),
            "voltage_policy_apply_to_defined": apply_to_defined,
        }]

    axes: List[Dict[str, Any]] = []
    for axis in resolve_voltage_axis(recipe_meta):
        tags = dict(axis or {})
        tags.update(
            {
                "voltage_policy_enabled": True,
                "voltage_policy_active": True,
                "voltage_policy_applied": True,
                "voltage_policy_status": "enabled",
                "voltage_policy_apply_to": list(apply_to),
                "voltage_policy_apply_to_defined": apply_to_defined,
            }
        )
        axes.append(tags)
    return axes or [{
        "voltage_policy_enabled": True,
        "voltage_policy_active": False,
        "voltage_policy_applied": False,
        "voltage_policy_status": "disabled_no_levels",
        "voltage_policy_apply_to": list(apply_to),
        "voltage_policy_apply_to_defined": apply_to_defined,
    }]


def resolve_data_rate_axis_for_test(recipe_meta: Dict[str, Any], *, standard: str, test_type: str) -> List[Dict[str, Any]]:
    policy = normalize_data_rate_policy(recipe_meta.get("data_rate_policy") or {})
    enabled = bool(policy.get("enabled"))
    apply_to, apply_to_defined = apply_to_is_restricted(
        policy.get("apply_to"),
        policy.get("apply_to_defined"),
    )
    current_test_type = normalize_test_type_symbol(test_type)
    applies = (not apply_to_defined) or (current_test_type in apply_to)
    by_standard = dict(policy.get("by_standard") or {})
    selected_data_rates = normalize_rate_list(recipe_meta.get("selected_data_rates") or [])
    allowed_rates = normalize_rate_list(by_standard.get(str(standard or "").strip()) or [])

    if not enabled:
        return [{
            "data_rate_policy_enabled": False,
            "data_rate_policy_active": False,
            "data_rate_policy_applied": False,
            "data_rate_policy_status": "disabled",
            "data_rate_policy_apply_to": list(apply_to),
            "data_rate_policy_apply_to_defined": apply_to_defined,
            "data_rate_standard": str(standard or "").strip(),
        }]
    if not applies:
        return [{
            "data_rate_policy_enabled": True,
            "data_rate_policy_active": False,
            "data_rate_policy_applied": False,
            "data_rate_policy_status": "not_applicable_test_type",
            "data_rate_policy_apply_to": list(apply_to),
            "data_rate_policy_apply_to_defined": apply_to_defined,
            "data_rate_standard": str(standard or "").strip(),
        }]
    if not allowed_rates:
        return [{
            "data_rate_policy_enabled": True,
            "data_rate_policy_active": False,
            "data_rate_policy_applied": False,
            "data_rate_policy_status": "disabled_no_standard_rates",
            "data_rate_policy_apply_to": list(apply_to),
            "data_rate_policy_apply_to_defined": apply_to_defined,
            "data_rate_standard": str(standard or "").strip(),
        }]

    effective_rates = [rate for rate in allowed_rates if not selected_data_rates or rate in selected_data_rates]
    if not effective_rates:
        return [{
            "data_rate_policy_enabled": True,
            "data_rate_policy_active": False,
            "data_rate_policy_applied": False,
            "data_rate_policy_status": "disabled_selected_subset_empty",
            "data_rate_policy_apply_to": list(apply_to),
            "data_rate_policy_apply_to_defined": apply_to_defined,
            "data_rate_standard": str(standard or "").strip(),
            "selected_data_rates": list(selected_data_rates),
        }]

    return [
        {
            "data_rate_policy_enabled": True,
            "data_rate_policy_active": True,
            "data_rate_policy_applied": True,
            "data_rate_policy_status": "enabled",
            "data_rate_policy_apply_to": list(apply_to),
            "data_rate_policy_apply_to_defined": apply_to_defined,
            "data_rate_standard": str(standard or "").strip(),
            "selected_data_rates": list(selected_data_rates),
            "data_rate": rate,
        }
        for rate in effective_rates
    ]


def _resolve_test_type_axis(context: AxisResolverContext) -> List[AxisPayload]:
    return [
        build_mapped_axis_payload("test_type", {"maps_to": "test_type"}, normalize_test_type_symbol(test_type))
        for test_type in list(context.recipe.test_types or [])
    ]


def _resolve_frequency_band_axis(context: AxisResolverContext) -> List[AxisPayload]:
    available = [str(name).strip() for name in dict(getattr(context.ruleset, "bands", {}) or {}).keys() if str(name).strip()]
    values = [str(v).strip() for v in (context.axis_def.get("values") or []) if str(v).strip()]
    candidates = values or available
    selected_band = str(context.recipe.band or "").strip()
    if selected_band:
        candidates = [selected_band] if selected_band in candidates or not values else []
    payloads: List[AxisPayload] = []
    for band in candidates:
        if not band:
            continue
        payload = build_mapped_axis_payload(context.axis_def.get("name", "frequency_band"), context.axis_def, band)
        payload["fields"]["band"] = band
        payloads.append(payload)
    return payloads


def _resolve_standard_axis(context: AxisResolverContext) -> List[AxisPayload]:
    wlan = dict(context.recipe_meta.get("wlan_expansion") or {})
    payloads: List[AxisPayload] = []
    mode_plan = list(wlan.get("mode_plan") or [])
    if mode_plan:
        for item in mode_plan:
            standard = str(item.get("standard", item.get("mode", ""))).strip() or str(context.recipe.standard or "").strip()
            if not standard:
                continue
            bandwidths: List[int] = []
            for bw in (item.get("bandwidths_mhz") or []):
                try:
                    bandwidths.append(int(bw))
                except Exception:
                    continue
            payload = build_mapped_axis_payload(context.axis_def.get("name", "standard"), context.axis_def, standard)
            payload["fields"]["standard"] = standard
            payload["fields"]["phy_mode"] = str(item.get("phy_mode", "") or "").strip()
            payload["fields"]["_mode_bandwidths"] = bandwidths
            payloads.append(payload)
        if payloads:
            return payloads

    standard = str(context.recipe.standard or "").strip()
    if standard:
        payload = build_mapped_axis_payload(context.axis_def.get("name", "standard"), context.axis_def, standard)
        payload["fields"]["standard"] = standard
        return [payload]

    values = [str(v).strip() for v in (context.axis_def.get("values") or []) if str(v).strip()]
    if values:
        return [build_mapped_axis_payload(context.axis_def.get("name", "standard"), context.axis_def, value) for value in values]

    band_info = band_info_for_state(context.ruleset, context.state)
    if band_info is not None:
        return [
            build_mapped_axis_payload(context.axis_def.get("name", "standard"), context.axis_def, value)
            for value in list(band_info.standards or [])
            if str(value).strip()
        ]
    return []


def _resolve_bandwidth_axis(context: AxisResolverContext) -> List[AxisPayload]:
    fields = dict(context.state.get("fields") or {})
    wlan = dict(context.recipe_meta.get("wlan_expansion") or {})
    channel_plan = list(wlan.get("channel_plan") or [])
    mode_bandwidths = [int(x) for x in (fields.get("_mode_bandwidths") or []) if x not in (None, "")]
    selected = [int(x) for x in (context.recipe.bandwidth_mhz or [])]
    values: List[int] = []
    if mode_bandwidths:
        values = list(mode_bandwidths)
    elif selected:
        values = list(selected)
    elif context.axis_def.get("values"):
        for item in (context.axis_def.get("values") or []):
            try:
                values.append(int(item))
            except Exception:
                continue

    if channel_plan and values:
        planned = {coerce_int(item.get("bandwidth_mhz"), -1) for item in channel_plan}
        values = [value for value in values if value in planned]

    out: List[AxisPayload] = []
    seen: set[int] = set()
    for bw in values:
        if bw in seen:
            continue
        seen.add(bw)
        payload = build_mapped_axis_payload(context.axis_def.get("name", "bandwidth"), context.axis_def, int(bw))
        payload["fields"]["bw_mhz"] = int(bw)
        out.append(payload)
    return out


def _resolve_channel_axis(context: AxisResolverContext) -> List[AxisPayload]:
    fields = dict(context.state.get("fields") or {})
    wlan = dict(context.recipe_meta.get("wlan_expansion") or {})
    channel_plan = list(wlan.get("channel_plan") or [])
    current_bw = coerce_int(fields.get("bw_mhz"), 0)
    current_band = str(fields.get("band", context.recipe.band) or "").strip()

    if channel_plan and current_bw:
        cp = next((item for item in channel_plan if coerce_int(item.get("bandwidth_mhz"), -1) == current_bw), None)
        if cp:
            channels = [coerce_int(x, 0) for x in (cp.get("channels") or [])]
            freqs = [coerce_float(x) for x in (cp.get("frequencies_mhz") or [])]
            out: List[AxisPayload] = []
            for idx, ch in enumerate(channels):
                if ch <= 0:
                    continue
                payload = build_mapped_axis_payload(context.axis_def.get("name", "channel"), context.axis_def, int(ch))
                payload["fields"]["channel"] = int(ch)
                cf = freqs[idx] if idx < len(freqs) and freqs[idx] is not None else (
                    center_freq_mhz_from_channel_5g(ch) if current_band == "5G" else 0.0
                )
                payload["fields"]["center_freq_mhz"] = float(cf)
                out.append(payload)
            return out

    band_info = dict(getattr(context.ruleset, "bands", {}) or {}).get(current_band)
    policy = dict(context.recipe.channel_policy or {})
    selected_channels: List[int] = []
    policy_name = str(policy.get("policy", "") or "").strip()
    if policy_name == "CUSTOM_LIST":
        selected_channels = [coerce_int(x, 0) for x in (policy.get("channels") or [])]
    elif policy_name == "ALL_CHANNELS" and band_info is not None:
        for group_obj in band_info.channel_groups.values():
            selected_channels.extend([int(x) for x in (group_obj.channels or [])])
    elif policy_name == "LOW_MID_HIGH_BY_GROUP" and band_info is not None:
        reps_override_all = dict(policy.get("representatives_override") or {})
        for group_name in (policy.get("groups") or []):
            group_obj = band_info.channel_groups.get(group_name)
            if group_obj is None:
                continue
            selected_channels.extend(pick_representatives_from_group(group_obj, reps_override_all.get(group_name, {}) or {}))
    elif context.axis_def.get("values"):
        for item in (context.axis_def.get("values") or []):
            try:
                selected_channels.append(int(item))
            except Exception:
                continue

    out: List[AxisPayload] = []
    seen: set[int] = set()
    for ch in sorted(set(int(x) for x in selected_channels if int(x) > 0)):
        if ch in seen:
            continue
        seen.add(ch)
        payload = build_mapped_axis_payload(context.axis_def.get("name", "channel"), context.axis_def, int(ch))
        payload["fields"]["channel"] = int(ch)
        payload["fields"]["center_freq_mhz"] = center_freq_mhz_from_channel_5g(ch) if current_band == "5G" else 0.0
        out.append(payload)
    return out


def _resolve_data_rate_policy_axis(context: AxisResolverContext) -> List[AxisPayload]:
    fields = dict(context.state.get("fields") or {})
    payloads = resolve_data_rate_axis_for_test(
        context.recipe_meta,
        standard=str(fields.get("standard", "") or ""),
        test_type=str(fields.get("test_type", "") or ""),
    )
    out: List[AxisPayload] = []
    for payload in payloads:
        row = dict(payload or {})
        out.append({
            "axis_value": str(row.get("data_rate", "") or ""),
            "fields": {},
            "tags": row,
            "key_suffix": data_rate_key_suffix(row),
        })
    return out


def _resolve_voltage_policy_axis(context: AxisResolverContext) -> List[AxisPayload]:
    fields = dict(context.state.get("fields") or {})
    payloads = resolve_voltage_axis_for_test(context.recipe_meta, str(fields.get("test_type", "") or ""))
    out: List[AxisPayload] = []
    for payload in payloads:
        row = dict(payload or {})
        out.append({
            "axis_value": str(row.get("voltage_condition", "") or ""),
            "fields": {},
            "tags": row,
            "key_suffix": voltage_key_suffix(row),
        })
    return out


def _resolve_static_axis(context: AxisResolverContext) -> List[AxisPayload]:
    axis_type = str(context.axis_def.get("type", "enum") or "enum").strip().lower()
    values = list(context.axis_def.get("values") or [])
    if values:
        payloads: List[AxisPayload] = []
        for item in values:
            axis_value = coerce_axis_scalar(axis_type, item)
            payloads.append(
                build_mapped_axis_payload(
                    context.axis_name,
                    context.axis_def,
                    axis_value,
                    key_suffix=generic_axis_key_suffix(context.axis_name, axis_value),
                )
            )
        return payloads
    return [empty_axis_payload(context.axis_name, context.axis_def, status="static_or_unconfigured", include_empty_value=False)]


register_axis_resolver(key="test_type", resolver=_resolve_test_type_axis)
register_axis_resolver(key="frequency_band", resolver=_resolve_frequency_band_axis)
register_axis_resolver(key="band", resolver=_resolve_frequency_band_axis)
register_axis_resolver(key="standard", resolver=_resolve_standard_axis)
register_axis_resolver(key="bandwidth", resolver=_resolve_bandwidth_axis)
register_axis_resolver(key="bw", resolver=_resolve_bandwidth_axis)
register_axis_resolver(key="channel", resolver=_resolve_channel_axis)
register_axis_resolver(key="data_rate", resolver=_resolve_data_rate_policy_axis)
register_axis_resolver(key="voltage", resolver=_resolve_voltage_policy_axis)

register_axis_resolver(key="bands", resolver=_resolve_frequency_band_axis, kind="source")
register_axis_resolver(key="preset.standard_or_wlan_expansion", resolver=_resolve_standard_axis, kind="source")
register_axis_resolver(key="preset.bandwidth_mhz", resolver=_resolve_bandwidth_axis, kind="source")
register_axis_resolver(key="channel_groups", resolver=_resolve_channel_axis, kind="source")
register_axis_resolver(key="data_rate_policy", resolver=_resolve_data_rate_policy_axis, kind="source")
register_axis_resolver(key="voltage_policy", resolver=_resolve_voltage_policy_axis, kind="source")

register_axis_resolver(key="enum", resolver=_resolve_static_axis, kind="type")
register_axis_resolver(key="numeric", resolver=_resolve_static_axis, kind="type")
register_axis_resolver(key="computed", resolver=_resolve_static_axis, kind="type")
register_axis_resolver(key="string", resolver=_resolve_static_axis, kind="type")
