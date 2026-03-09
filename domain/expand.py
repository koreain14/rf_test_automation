from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .models import InstrumentProfile, Preset, Recipe, RuleSet, TestCase
from .ruleset_models import BandInfo, ChannelGroup  # <- 네가 만든 위치에 맞게 import 경로 수정


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
    # 기본 representatives
    reps = dict(group.representatives or {})

    # override 적용
    if rep_override:
        reps.update({str(k).upper(): int(v) for k, v in rep_override.items()})

    if reps:
        out: List[int] = []
        for k in ("LOW", "MID", "HIGH"):
            v = reps.get(k)
            if v is not None and v not in out:
                out.append(int(v))
        return out

    # representatives가 없으면 channels에서 low/mid/high 계산
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


def build_recipe(ruleset: RuleSet, preset: Preset) -> Recipe:
    sel = preset.selection

    band = sel["band"]
    standard = sel["standard"]
    plan_mode = sel.get("plan_mode", "Quick")
    test_types = list(sel.get("test_types", []))
    bw_list = list(sel.get("bandwidth_mhz", []))
    channel_policy = dict(sel.get("channels", {}))

    ip_by_test: Dict[str, InstrumentProfile] = {}
    ip_map = sel.get("instrument_profile_by_test", {})
    for t in test_types:
        prof_name = ip_map.get(t, "PSD_DEFAULT")
        ip = ruleset.instrument_profiles.get(prof_name)
        if ip is None:
            raise ValueError(f"Instrument profile not found: {prof_name}")
        ip_by_test[t] = ip

    meta = {"preset_name": preset.name}
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
    # (기존 코드 끝에 있던 band 존재 체크는 여기로 올리는 게 맞음)
    if recipe.band not in ruleset.bands:
        raise ValueError(
            f"Band '{recipe.band}' not defined in ruleset '{ruleset.id}'. "
            f"Available: {list(ruleset.bands.keys())}"
        )

    band_info: BandInfo = ruleset.bands[recipe.band]

    pol = recipe.channel_policy
    policy = pol.get("policy")

    channels: List[int] = []

    if policy == "LOW_MID_HIGH_BY_GROUP":
        grouping = pol.get("grouping", "UNII")
        groups = pol.get("groups", [])
        reps_override_all = pol.get("representatives_override", {}) or {}

        if grouping != "UNII":
            raise ValueError(f"Unsupported grouping: {grouping}")

        cg = band_info.channel_groups  # Dict[str, ChannelGroup]
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

    # group 태깅
    def find_group(ch: int) -> str:
        for gname, group_obj in band_info.channel_groups.items():
            if ch in (group_obj.channels or []):
                return gname
        return ""

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