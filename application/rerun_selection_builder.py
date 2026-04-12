from __future__ import annotations

from typing import Any, Dict, Iterable

from application.test_type_symbols import normalize_test_type_list


def build_rerun_selection(
    *,
    base_selection: Dict[str, Any],
    selected_rows: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    selection = dict(base_selection or {})
    rows = [dict(row or {}) for row in (selected_rows or [])]
    if not rows:
        return selection

    selected_tests = normalize_test_type_list(
        sorted({str(row.get("test_type") or "").strip() for row in rows if str(row.get("test_type") or "").strip()})
    )
    selected_bandwidths = sorted({
        int(row.get("bw_mhz"))
        for row in rows
        if row.get("bw_mhz") not in (None, "")
    })
    selected_channels = sorted({
        int(row.get("channel"))
        for row in rows
        if row.get("channel") not in (None, "")
    })
    selected_standards = _ordered_unique_strings(row.get("standard") for row in rows)

    if not selected_tests or not selected_bandwidths or not selected_channels:
        raise ValueError("Selected rows must include test_type, bw_mhz, channel.")

    selection["test_types"] = selected_tests
    selection["bandwidth_mhz"] = selected_bandwidths
    selection["channels"] = {
        "policy": "CUSTOM_LIST",
        "channels": selected_channels,
    }
    selection["standard"] = selected_standards[0] if len(selected_standards) == 1 else ""

    wlan = _extract_wlan_expansion(selection)
    if wlan:
        narrowed = _narrow_wlan_expansion(wlan=wlan, rows=rows)
        if narrowed:
            selection["wlan_expansion"] = narrowed
        else:
            selection.pop("wlan_expansion", None)

        metadata = dict(selection.get("metadata") or {})
        metadata.pop("wlan_expansion", None)
        if metadata:
            selection["metadata"] = metadata
        else:
            selection.pop("metadata", None)

    return selection


def _extract_wlan_expansion(selection: Dict[str, Any]) -> Dict[str, Any]:
    wlan = dict(selection.get("wlan_expansion") or {})
    if wlan:
        return wlan
    metadata = dict(selection.get("metadata") or {})
    return dict(metadata.get("wlan_expansion") or {})


def _narrow_wlan_expansion(*, wlan: Dict[str, Any], rows: list[Dict[str, Any]]) -> Dict[str, Any]:
    selected_bw_to_channels: Dict[int, set[int]] = {}
    selected_standards_by_bw: Dict[int, set[str]] = {}
    selected_standards: set[str] = set()

    for row in rows:
        standard = str(row.get("standard") or "").strip()
        if standard:
            selected_standards.add(standard)
        try:
            bw = int(row.get("bw_mhz"))
            ch = int(row.get("channel"))
        except Exception:
            continue
        selected_bw_to_channels.setdefault(bw, set()).add(ch)
        if standard:
            selected_standards_by_bw.setdefault(bw, set()).add(standard)

    mode_plan_out = []
    for item in (wlan.get("mode_plan") or []):
        row = dict(item or {})
        standard = str(row.get("standard", row.get("mode", "")) or "").strip()
        if selected_standards and standard and standard not in selected_standards:
            continue
        narrowed_bandwidths = []
        for raw_bw in (row.get("bandwidths_mhz") or []):
            try:
                bw = int(raw_bw)
            except Exception:
                continue
            if bw not in selected_bw_to_channels:
                continue
            if standard and selected_standards_by_bw.get(bw) and standard not in selected_standards_by_bw[bw]:
                continue
            narrowed_bandwidths.append(bw)
        narrowed_bandwidths = _ordered_unique_ints(narrowed_bandwidths)
        if not narrowed_bandwidths:
            continue
        mode_plan_out.append(
            {
                "standard": standard,
                "phy_mode": str(row.get("phy_mode", "") or "").strip(),
                "bandwidths_mhz": narrowed_bandwidths,
            }
        )

    channel_plan_out = []
    for item in (wlan.get("channel_plan") or []):
        row = dict(item or {})
        try:
            bw = int(row.get("bandwidth_mhz"))
        except Exception:
            continue
        selected_channels = selected_bw_to_channels.get(bw)
        if not selected_channels:
            continue

        channels = list(row.get("channels") or [])
        freqs = list(row.get("frequencies_mhz") or [])
        narrowed_channels = []
        narrowed_freqs = []
        for idx, raw_channel in enumerate(channels):
            try:
                channel = int(raw_channel)
            except Exception:
                continue
            if channel not in selected_channels:
                continue
            narrowed_channels.append(channel)
            if idx < len(freqs):
                try:
                    narrowed_freqs.append(float(freqs[idx]))
                except Exception:
                    pass
        if not narrowed_channels:
            continue
        channel_plan_out.append(
            {
                "bandwidth_mhz": bw,
                "channels": narrowed_channels,
                "frequencies_mhz": narrowed_freqs,
            }
        )

    if not mode_plan_out or not channel_plan_out:
        return {}

    return {
        "mode_plan": mode_plan_out,
        "channel_plan": channel_plan_out,
    }


def _ordered_unique_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _ordered_unique_ints(values: Iterable[Any]) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            ivalue = int(value)
        except Exception:
            continue
        if ivalue in seen:
            continue
        seen.add(ivalue)
        out.append(ivalue)
    return out
