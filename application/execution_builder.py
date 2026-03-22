from __future__ import annotations

from typing import Any, Dict, List
from uuid import uuid4

from domain.execution import MeasurementStep


class ExecutionBuilder:
    def build_steps_for_case(self, run_id: str, case: Dict[str, Any]) -> List[MeasurementStep]:
        test_type = str(case.get("test_type", "")).strip().upper()
        if not test_type:
            raise ValueError("Case is missing test_type")

        step = MeasurementStep(
            step_id=self._new_step_id(),
            run_id=run_id,
            case_id=self._case_id(case),
            technology=str(case.get("technology", "WLAN") or "WLAN"),
            test_type=test_type,
            step_type=f"RUN_{test_type}",
            order_index=0,
            name=self._build_step_name(case),
            ruleset_id=str(case.get("ruleset_id", "")),
            band=str(case.get("band", "")),
            standard=str(case.get("standard", "")),
            phy_mode=str(case.get("phy_mode", "")),
            bandwidth_mhz=self._safe_int(case.get("bandwidth_mhz") or case.get("bw_mhz")),
            channel=self._safe_int(case.get("channel")),
            frequency_mhz=self._safe_float(case.get("frequency_mhz") or case.get("center_freq_mhz")),
            instrument_profile_name=self._resolve_instrument_profile(case),
            parameters=self._build_parameters(case),
            required_capabilities=self._required_capabilities(test_type),
            metadata={
                "group": str((case.get("tags") or {}).get("group", "")),
                "test_key": str(case.get("key", "")),
            },
        )
        return [step]

    def _new_step_id(self) -> str:
        return uuid4().hex

    def _case_id(self, case: Dict[str, Any]) -> str:
        for key in ("id", "case_id", "key"):
            value = case.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    def _build_step_name(self, case: Dict[str, Any]) -> str:
        return (
            f'{case.get("test_type", "")} | '
            f'CH{case.get("channel", "")} | '
            f'{self._safe_int(case.get("bandwidth_mhz") or case.get("bw_mhz"))}MHz | '
            f'{case.get("standard", "")}'
        )

    def _resolve_instrument_profile(self, case: Dict[str, Any]) -> str:
        profile = str(case.get("instrument_profile_name", "")).strip()
        if profile:
            return profile
        instrument_snapshot = case.get("instrument") or {}
        if isinstance(instrument_snapshot, dict):
            by_test = instrument_snapshot.get("profile_name")
            if by_test:
                return str(by_test)
        fallback = {
            "PSD": "PSD_DEFAULT",
            "OBW": "OBW_DEFAULT",
            "CHANNEL_POWER": "TXP_DEFAULT",
            "TX_SPURIOUS": "SP_DEFAULT",
            "SP": "SP_DEFAULT",
            "RX_SPURIOUS": "SP_DEFAULT",
            "FE": "SP_DEFAULT",
            "RX": "RX_DEFAULT",
        }
        test_type = str(case.get("test_type", "")).strip().upper()
        return fallback.get(test_type, "")

    def _build_parameters(self, case: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ruleset_id": case.get("ruleset_id", ""),
            "band": case.get("band", ""),
            "standard": case.get("standard", ""),
            "phy_mode": case.get("phy_mode", ""),
            "bandwidth_mhz": self._safe_int(case.get("bandwidth_mhz") or case.get("bw_mhz")),
            "channel": self._safe_int(case.get("channel")),
            "frequency_mhz": self._safe_float(case.get("frequency_mhz") or case.get("center_freq_mhz")),
        }

    def _required_capabilities(self, test_type: str) -> List[str]:
        caps = {
            "PSD": ["analyzer"],
            "OBW": ["analyzer"],
            "CHANNEL_POWER": ["analyzer"],
            "TX_SPURIOUS": ["analyzer"],
            "SP": ["analyzer"],
            "RX": ["analyzer"],
        }
        return caps.get(test_type, [])

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            if value in (None, ""):
                return default
            return int(value)
        except Exception:
            return default

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except Exception:
            return default
