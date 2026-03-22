from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .models import InstrumentProfile, Preset, Recipe, RuleSet, TestCase
from .ruleset_models import BandInfo, ChannelGroup


def center_freq_mhz_from_channel_5g(ch: int) -> float:
    return 5000 + 5 * ch


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
    test_types = [str(x) for x in (sel.get("test_types") or []) if str(x).strip()]

    wlan = _extract_wlan_expansion(sel)
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
    ip_map = dict(sel.get("instrument_profile_by_test") or {})
    default_profile_by_test = {
        "PSD": "PSD_DEFAULT",
        "OBW": "OBW_DEFAULT",
        "SP": "SP_DEFAULT",
        "RX": "SP_DEFAULT",
        "TX_SPURIOUS": "SP_DEFAULT",
        "RX_SPURIOUS": "SP_DEFAULT",
        "FE": "SP_DEFAULT",
        "CHANNEL_POWER": "TXP_DEFAULT",
        "TXP": "TXP_DEFAULT",
    }
    for t in test_types:
        prof_name = ip_map.get(t) or default_profile_by_test.get(t) or "PSD_DEFAULT"
        ip = ruleset.instrument_profiles.get(prof_name)
        if ip is None and t in default_profile_by_test:
            ip = ruleset.instrument_profiles.get(default_profile_by_test[t])
        if ip is None:
            raise ValueError(f"Instrument profile not found for test '{t}': {prof_name}")
        ip_by_test[t] = ip

    meta = {
        "preset_name": preset.name,
        "wlan_expansion": wlan,
    }
    pol = sel.get("execution_policy")
    if pol:
        meta["execution_policy"] = pol
    else:
        meta["execution_policy"] = {
            "type": "CHANNEL_CENTRIC",
            "test_order": ["PSD", "OBW", "SP", "RX"],
            "include_bw_in_group": True,
        }

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
                        key = f"{recipe.tech}|{recipe.regulation}|{recipe.band}|{standard}|{phy_mode}|{test}|CH{ch}|BW{bw}"
                        yield TestCase(
                            test_type=test,
                            band=recipe.band,
                            standard=standard,
                            channel=ch,
                            center_freq_mhz=cf,
                            bw_mhz=bw,
                            instrument=dict(ip.settings),
                            tags={
                                "plan_mode": recipe.plan_mode,
                                "preset": recipe.meta.get("preset_name", ""),
                                "group": find_group(ch),
                                "phy_mode": phy_mode,
                            },
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
                key = f"{recipe.tech}|{recipe.regulation}|{recipe.band}|{recipe.standard}|{test}|CH{ch}|BW{bw}"
                yield TestCase(
                    test_type=test,
                    band=recipe.band,
                    standard=recipe.standard,
                    channel=ch,
                    center_freq_mhz=cf,
                    bw_mhz=bw,
                    instrument=dict(ip.settings),
                    tags={
                        "plan_mode": recipe.plan_mode,
                        "preset": recipe.meta.get("preset_name", ""),
                        "group": find_group(ch),
                    },
                    key=key,
                )
