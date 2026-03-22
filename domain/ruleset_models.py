from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ChannelGroup:
    name: str
    channels: List[int]
    dfs_required: bool
    representatives: Dict[str, int]  # {"LOW": 1, "MID": 6, "HIGH": 11}

    @staticmethod
    def from_dict(name: str, d: Dict[str, Any]) -> "ChannelGroup":
        if not isinstance(d, dict):
            raise TypeError(f"ChannelGroup '{name}' must be dict, got {type(d)}")

        channels = d.get("channels", [])
        if channels is None:
            channels = []
        if not isinstance(channels, list):
            raise TypeError(f"ChannelGroup '{name}'.channels must be list, got {type(channels)}")

        reps = d.get("representatives", {}) or {}
        if not isinstance(reps, dict):
            raise TypeError(f"ChannelGroup '{name}'.representatives must be dict, got {type(reps)}")

        # int로 정규화
        channels_int = [int(x) for x in channels]
        reps_int = {str(k): int(v) for k, v in reps.items()}

        dfs_required = bool(d.get("dfs_required", False))

        return ChannelGroup(
            name=str(name),
            channels=channels_int,
            dfs_required=dfs_required,
            representatives=reps_int,
        )


@dataclass(frozen=True)
class BandInfo:
    band: str  # "2.4G" / "5G" / "6G"
    standards: List[str]
    tests_supported: List[str]
    channel_groups: Dict[str, ChannelGroup]
    device_classes: Optional[List[str]] = None  # 6G에만 존재할 수 있음

    @staticmethod
    def from_dict(band: str, d: Dict[str, Any]) -> "BandInfo":
        if not isinstance(d, dict):
            raise TypeError(f"BandInfo '{band}' must be dict, got {type(d)}")

        standards = d.get("standards", []) or []
        if not isinstance(standards, list):
            raise TypeError(f"BandInfo '{band}'.standards must be list, got {type(standards)}")

        tests_supported = d.get("tests_supported", []) or []
        if not isinstance(tests_supported, list):
            raise TypeError(f"BandInfo '{band}'.tests_supported must be list, got {type(tests_supported)}")

        device_classes = d.get("device_classes", None)
        if device_classes is not None and not isinstance(device_classes, list):
            raise TypeError(f"BandInfo '{band}'.device_classes must be list or None, got {type(device_classes)}")

        cg_raw = d.get("channel_groups", {}) or {}
        if not isinstance(cg_raw, dict):
            raise TypeError(f"BandInfo '{band}'.channel_groups must be dict, got {type(cg_raw)}")

        channel_groups: Dict[str, ChannelGroup] = {
            str(name): ChannelGroup.from_dict(str(name), cg_dict)
            for name, cg_dict in cg_raw.items()
        }

        return BandInfo(
            band=str(band),
            standards=[str(x) for x in standards],
            tests_supported=[str(x) for x in tests_supported],
            channel_groups=channel_groups,
            device_classes=[str(x) for x in device_classes] if device_classes is not None else None,
        )


@dataclass(frozen=True)
class InstrumentProfile:
    rbw_hz: int
    vbw_hz: int
    detector: str
    trace_mode: str

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "InstrumentProfile":
        if not isinstance(d, dict):
            raise TypeError(f"InstrumentProfile must be dict, got {type(d)}")

        return InstrumentProfile(
            rbw_hz=int(d.get("rbw_hz", 0)),
            vbw_hz=int(d.get("vbw_hz", 0)),
            detector=str(d.get("detector", "")),
            trace_mode=str(d.get("trace_mode", "")),
        )


@dataclass(frozen=True)
class PlanMode:
    name: str
    channel_policy: str

    @staticmethod
    def from_dict(name: str, d: Dict[str, Any]) -> "PlanMode":
        if not isinstance(d, dict):
            raise TypeError(f"PlanMode '{name}' must be dict, got {type(d)}")
        return PlanMode(
            name=str(name),
            channel_policy=str(d.get("channel_policy", "")),
        )

@dataclass(frozen=True)
class RuleSet:
    id: str
    version: str
    regulation: str
    tech: str
    bands: Dict[str, BandInfo]
    instrument_profiles: Dict[str, InstrumentProfile]
    plan_modes: Dict[str, PlanMode]

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RuleSet":
        if not isinstance(d, dict):
            raise TypeError(f"RuleSet must be dict, got {type(d)}")

        rs_id = str(d.get("id", "")).strip()
        if not rs_id:
            raise KeyError("RuleSet.from_dict: missing 'id'")

        bands_raw = d.get("bands", {}) or {}
        if not isinstance(bands_raw, dict):
            raise TypeError(f"RuleSet.bands must be dict, got {type(bands_raw)}")

        bands: Dict[str, BandInfo] = {
            str(band): BandInfo.from_dict(str(band), band_dict)
            for band, band_dict in bands_raw.items()
        }

        ip_raw = d.get("instrument_profiles", {}) or {}
        if not isinstance(ip_raw, dict):
            raise TypeError(f"RuleSet.instrument_profiles must be dict, got {type(ip_raw)}")
        instrument_profiles = {
            str(k): InstrumentProfile.from_dict(v) for k, v in ip_raw.items()
        }

        pm_raw = d.get("plan_modes", {}) or {}
        if not isinstance(pm_raw, dict):
            raise TypeError(f"RuleSet.plan_modes must be dict, got {type(pm_raw)}")
        plan_modes = {str(k): PlanMode.from_dict(v) for k, v in pm_raw.items()}

        return RuleSet(
            id=rs_id,
            version=str(d.get("version", "")).strip(),
            regulation=str(d.get("regulation", "")).strip(),
            tech=str(d.get("tech", "")).strip(),
            bands=bands,
            instrument_profiles=instrument_profiles,
            plan_modes=plan_modes,
        )