from __future__ import annotations

from application.preset_model import PresetModel
from application.preset_validation_models import PresetValidationResult
from application.preset_validators.base_validator import BasePresetExtensionValidator


class WlanPresetValidator(BasePresetExtensionValidator):
    def validate(self, model: PresetModel, result: PresetValidationResult) -> None:
        sel = model.selection
        wlan_model = sel.wlan_expansion
        if wlan_model is None:
            meta = dict(sel.metadata or {})
            wlan = dict(meta.get("wlan_expansion") or {})
            if not wlan:
                return
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

        if not mode_plan:
            result.add_error("WLAN expansion requires at least one mode plan row.")
        if not channel_plan:
            result.add_error("WLAN expansion requires at least one channel plan row.")

        available_bandwidths: set[int] = set()
        standards_in_plan: set[str] = set()
        seen_rows: set[tuple[str, str, tuple[int, ...]]] = set()
        duplicate_rows: list[str] = []

        for idx, item in enumerate(mode_plan, start=1):
            standard = str(item.get("standard", item.get("mode", ""))).strip()
            phy_mode = str(item.get("phy_mode", "")).strip()
            if not standard:
                result.add_error(f"WLAN mode row {idx}: standard is required.")
            else:
                standards_in_plan.add(standard)
            if not phy_mode:
                result.add_error(f"WLAN mode row {idx}: PHY mode is required.")

            bws = item.get("bandwidths_mhz") or []
            if not bws:
                result.add_error(f"WLAN mode row {idx}: at least one bandwidth is required.")
                continue

            try:
                bw_tuple = tuple(int(bw) for bw in bws)
            except Exception:
                bw_tuple = tuple()
            row_key = (standard, phy_mode, bw_tuple)
            if row_key in seen_rows and row_key not in duplicate_rows:
                duplicate_rows.append(f"{standard}|{phy_mode}|{','.join(str(x) for x in bw_tuple)}")
            seen_rows.add(row_key)

            for bw in bws:
                try:
                    available_bandwidths.add(int(bw))
                except Exception:
                    result.add_error(f"Invalid WLAN bandwidth in mode plan: {bw}")

        declared_channel_bws: set[int] = set()
        for item in channel_plan:
            try:
                bw = int(item.get("bandwidth_mhz"))
            except Exception:
                result.add_error(f"Invalid WLAN channel plan bandwidth: {item.get('bandwidth_mhz')}")
                continue
            declared_channel_bws.add(bw)
            channels = [int(x) for x in (item.get("channels") or [])]
            freqs = [float(x) for x in (item.get("frequencies_mhz") or [])]
            if not channels:
                result.add_error(f"WLAN channel plan for {bw} MHz must define channels.")
            if freqs and len(freqs) != len(channels):
                result.add_error(
                    f"WLAN channel/frequency count mismatch for {bw} MHz: "
                    f"channels={len(channels)} frequencies={len(freqs)}"
                )

        missing = sorted(available_bandwidths - declared_channel_bws)
        if missing:
            result.add_error(f"WLAN channel plan is missing bandwidth mapping for: {missing} MHz")

        if duplicate_rows:
            result.add_warning(f"Duplicate WLAN mode plan rows found: {duplicate_rows}")

        if len(standards_in_plan) > 1 and sel.standard.strip() and sel.standard.strip() not in standards_in_plan:
            result.add_warning(
                "General tab standard is not included in WLAN expansion rows. "
                "WLAN expansion rows will be used for preview/build."
            )
        elif len(standards_in_plan) > 1:
            result.add_warning(
                "General tab standard acts only as a summary when WLAN expansion contains multiple standards."
            )
