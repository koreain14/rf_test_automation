from __future__ import annotations

from typing import Any

from application.plan_builders.base_builder import BasePlanBuilder
from application.preset_model import PresetModel


class WlanPlanBuilder(BasePlanBuilder):
    """
    Build valid WLAN plan combinations from preset selection metadata.

    The builder is intentionally isolated from the existing RuleSet expand flow.
    It is used by the Preset Editor to validate and preview WLAN-specific
    expansion rules without changing the runtime execution path.
    """

    def build_steps(self, model: PresetModel) -> list[dict[str, Any]]:
        selection = model.selection
        wlan_model = selection.wlan_expansion
        if wlan_model is None:
            meta = dict(selection.metadata or {})
            wlan = dict(meta.get("wlan_expansion") or {})
            mode_plan = list(wlan.get("mode_plan") or [])
            channel_plan = list(wlan.get("channel_plan") or [])
        else:
            mode_plan = [
                {
                    "standard": row.standard,
                    "phy_mode": row.phy_mode,
                    "bandwidths_mhz": list(row.bandwidths_mhz),
                }
                for row in wlan_model.mode_plan
            ]
            channel_plan = [
                {
                    "bandwidth_mhz": row.bandwidth_mhz,
                    "channels": list(row.channels),
                    "frequencies_mhz": list(row.frequencies_mhz),
                }
                for row in wlan_model.channel_plan
            ]

        if not mode_plan or not channel_plan:
            return self._build_legacy_steps(model)

        tests = [str(t) for t in selection.test_types if str(t).strip()]
        steps: list[dict[str, Any]] = []
        for mode_item in mode_plan:
            standard = str(mode_item.get("standard", mode_item.get("mode", ""))).strip()
            phy_mode = str(mode_item.get("phy_mode", "")).strip()
            if not standard:
                continue
            bandwidths = [int(x) for x in (mode_item.get("bandwidths_mhz") or [])]
            for bw in bandwidths:
                cp = self._find_channel_plan(channel_plan, bw)
                if not cp:
                    continue
                channels = [int(x) for x in (cp.get("channels") or [])]
                freqs = [float(x) for x in (cp.get("frequencies_mhz") or [])]
                for idx, ch in enumerate(channels):
                    freq = freqs[idx] if idx < len(freqs) else None
                    for test_type in tests:
                        steps.append({
                            "technology": "WLAN",
                            "ruleset_id": model.ruleset_id,
                            "band": selection.band,
                            "standard": standard,
                            "phy_mode": phy_mode,
                            "bandwidth_mhz": bw,
                            "channel": ch,
                            "frequency_mhz": freq,
                            "test_type": test_type,
                            "plan_mode": selection.plan_mode,
                        })
        return steps

    @staticmethod
    def _find_channel_plan(channel_plan: list[dict[str, Any]], bandwidth_mhz: int) -> dict[str, Any] | None:
        for item in channel_plan:
            try:
                if int(item.get("bandwidth_mhz")) == int(bandwidth_mhz):
                    return item
            except Exception:
                continue
        return None

    @staticmethod
    def _build_legacy_steps(model: PresetModel) -> list[dict[str, Any]]:
        selection = model.selection
        tests = [str(t) for t in selection.test_types if str(t).strip()]
        steps: list[dict[str, Any]] = []
        for bw in selection.bandwidth_mhz:
            for ch in selection.channels.channels:
                for test_type in tests:
                    steps.append({
                        "technology": "WLAN",
                        "ruleset_id": model.ruleset_id,
                        "band": selection.band,
                        "standard": selection.standard,
                        "phy_mode": "",
                        "bandwidth_mhz": int(bw),
                        "channel": int(ch),
                        "frequency_mhz": None,
                        "test_type": test_type,
                        "plan_mode": selection.plan_mode,
                    })
        return steps
