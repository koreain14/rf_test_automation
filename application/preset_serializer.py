from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from application.preset_model import (
    ChannelSelectionModel,
    ExecutionPolicyModel,
    PresetModel,
    PresetSelectionModel,
    WlanChannelRowModel,
    WlanExpansionModel,
    WlanModeRowModel,
)
from application.test_type_symbols import DEFAULT_TEST_ORDER, normalize_test_type_list, normalize_test_type_map


class PresetSerializer:
    @staticmethod
    def from_dict(data: dict[str, Any]) -> PresetModel:
        selection_raw = dict(data.get("selection") or {})
        channels_raw = dict(selection_raw.get("channels") or {})
        exec_raw = dict(selection_raw.get("execution_policy") or {})

        wlan_expansion = _parse_wlan_expansion(selection_raw)
        bandwidth_summary = [int(x) for x in (selection_raw.get("bandwidth_mhz") or [])]
        channel_summary = [int(x) for x in (channels_raw.get("channels") or [])]
        summary_standard = str(selection_raw.get("standard", ""))
        if wlan_expansion is not None:
            if not bandwidth_summary:
                bandwidth_summary = _derive_bandwidth_summary(wlan_expansion)
            if not channel_summary:
                channel_summary = _derive_channel_summary(wlan_expansion)
            if not summary_standard:
                summary_standard = _derive_standard_summary(wlan_expansion)

        selection = PresetSelectionModel(
            band=str(selection_raw.get("band", "")),
            standard=summary_standard,
            plan_mode=str(selection_raw.get("plan_mode", "DEMO")),
            test_types=normalize_test_type_list(selection_raw.get("test_types") or []),
            bandwidth_mhz=bandwidth_summary,
            channels=ChannelSelectionModel(
                policy=str(channels_raw.get("policy", "CUSTOM_LIST")),
                channels=channel_summary,
                grouping=str(channels_raw.get("grouping", "")),
                groups=[str(x) for x in (channels_raw.get("groups") or [])],
                representatives_override=dict(channels_raw.get("representatives_override") or {}),
            ),
            execution_policy=ExecutionPolicyModel(
                type=str(exec_raw.get("type", "CHANNEL_CENTRIC")),
                test_order=normalize_test_type_list(exec_raw.get("test_order") or []) or list(DEFAULT_TEST_ORDER),
                include_bw_in_group=bool(exec_raw.get("include_bw_in_group", True)),
            ),
            instrument_profile_by_test=normalize_test_type_map(selection_raw.get("instrument_profile_by_test") or {}),
            device_class=str(selection_raw.get("device_class", "")),
            defaults=dict(selection_raw.get("defaults") or {}),
            metadata=dict(selection_raw.get("metadata") or {}),
            wlan_expansion=wlan_expansion,
        )

        return PresetModel(
            schema_version=int(data.get("schema_version", 3)),
            name=str(data.get("name", "")),
            ruleset_id=str(data.get("ruleset_id", "")),
            ruleset_version=str(data.get("ruleset_version", "")),
            selection=selection,
            description=str(data.get("description", "")),
        )

    @staticmethod
    def to_dict(model: PresetModel) -> dict[str, Any]:
        out = asdict(model)
        out.pop("source_path", None)
        out.pop("is_builtin", None)

        out["schema_version"] = 3
        selection = out.get("selection") or {}
        selection["test_types"] = normalize_test_type_list(selection.get("test_types") or [])
        execution_policy = dict(selection.get("execution_policy") or {})
        execution_policy["test_order"] = normalize_test_type_list(execution_policy.get("test_order") or []) or list(DEFAULT_TEST_ORDER)
        selection["execution_policy"] = execution_policy
        selection["instrument_profile_by_test"] = normalize_test_type_map(selection.get("instrument_profile_by_test") or {})
        wlan_payload = _serialize_wlan_expansion(model.selection.wlan_expansion)
        selection["wlan_expansion"] = wlan_payload
        if model.selection.standard.strip():
            selection["standard"] = model.selection.standard.strip()
        else:
            selection.pop("standard", None)
        selection.pop("bandwidth_mhz", None)
        selection.pop("channels", None)
        selection.pop("metadata", None)
        out["selection"] = selection
        return out

    @staticmethod
    def load_file(path: Path) -> PresetModel:
        raw = json.loads(path.read_text(encoding="utf-8"))
        model = PresetSerializer.from_dict(raw)
        model.source_path = str(path)
        return model

    @staticmethod
    def save_file(model: PresetModel, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = PresetSerializer.to_dict(model)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_wlan_expansion(selection_raw: dict[str, Any]) -> WlanExpansionModel | None:
    wlan_raw = selection_raw.get("wlan_expansion")
    if not wlan_raw:
        wlan_raw = (selection_raw.get("metadata") or {}).get("wlan_expansion")
    if not wlan_raw:
        return None

    wlan_raw = dict(wlan_raw)
    mode_plan: list[WlanModeRowModel] = []
    for item in (wlan_raw.get("mode_plan") or []):
        row = dict(item or {})
        standard = str(row.get("standard", row.get("mode", ""))).strip()
        phy_mode = str(row.get("phy_mode", "")).strip()
        mode_plan.append(
            WlanModeRowModel(
                standard=standard,
                phy_mode=phy_mode,
                bandwidths_mhz=[int(x) for x in (row.get("bandwidths_mhz") or [])],
            )
        )

    channel_plan: list[WlanChannelRowModel] = []
    for item in (wlan_raw.get("channel_plan") or []):
        row = dict(item or {})
        channel_plan.append(
            WlanChannelRowModel(
                bandwidth_mhz=int(row.get("bandwidth_mhz", 20)),
                channels=[int(x) for x in (row.get("channels") or [])],
                frequencies_mhz=[float(x) for x in (row.get("frequencies_mhz") or [])],
            )
        )

    return WlanExpansionModel(mode_plan=mode_plan, channel_plan=channel_plan)


def _serialize_wlan_expansion(model: WlanExpansionModel | None) -> dict[str, Any]:
    if not model:
        return {}
    return {
        "mode_plan": [
            {
                "standard": row.standard,
                "phy_mode": row.phy_mode,
                "bandwidths_mhz": list(row.bandwidths_mhz),
            }
            for row in model.mode_plan
        ],
        "channel_plan": [
            {
                "bandwidth_mhz": row.bandwidth_mhz,
                "channels": list(row.channels),
                "frequencies_mhz": list(row.frequencies_mhz),
            }
            for row in model.channel_plan
        ],
    }


def _derive_standard_summary(model: WlanExpansionModel) -> str:
    standards = []
    for row in model.mode_plan:
        standard = str(row.standard).strip()
        if standard and standard not in standards:
            standards.append(standard)
    return standards[0] if len(standards) == 1 else ""


def _derive_bandwidth_summary(model: WlanExpansionModel) -> list[int]:
    out: list[int] = []
    for row in model.mode_plan:
        for bw in row.bandwidths_mhz:
            ibw = int(bw)
            if ibw not in out:
                out.append(ibw)
    for row in model.channel_plan:
        ibw = int(row.bandwidth_mhz)
        if ibw not in out:
            out.append(ibw)
    return sorted(out)


def _derive_channel_summary(model: WlanExpansionModel) -> list[int]:
    out: list[int] = []
    for row in model.channel_plan:
        for ch in row.channels:
            ich = int(ch)
            if ich not in out:
                out.append(ich)
    return sorted(out)
