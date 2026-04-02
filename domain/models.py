from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


Regulation = Literal["KC", "CE", "FCC"]
Tech = Literal["WLAN", "BT", "UWB", "OTHER"]
PlanMode = Literal["Quick", "Worst", "Full"]


@dataclass(frozen=True)
class InstrumentProfile:
    name: str
    settings: Dict[str, Any]


@dataclass(frozen=True)
class RuleSet:
    id: str
    version: str
    regulation: Regulation
    tech: Tech
    bands: Dict[str, Dict[str, Any]]
    instrument_profiles: Dict[str, InstrumentProfile] = field(default_factory=dict)
    plan_modes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    test_contracts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    test_labels: Dict[str, str] = field(default_factory=dict)
    voltage_policy: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Preset:
    name: str
    ruleset_id: str
    ruleset_version: str
    selection: Dict[str, Any]
    description: str = ""


@dataclass(frozen=True)
class Recipe:
    ruleset_id: str
    ruleset_version: str
    regulation: Regulation
    tech: Tech
    band: str
    standard: str
    plan_mode: PlanMode
    test_types: List[str]
    bandwidth_mhz: List[int]
    channel_policy: Dict[str, Any]
    instrument_profile_by_test: Dict[str, InstrumentProfile]
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Match:
    band: Optional[str] = None
    standard: Optional[str] = None
    test_type: Optional[str] = None
    channel: Optional[int] = None
    bw_mhz: Optional[int] = None
    group: Optional[str] = None
    segment: Optional[str] = None
    device_class: Optional[str] = None
    channels: Optional[List[int]] = None


OverrideAction = Literal["set", "skip"]


@dataclass(frozen=True)
class OverrideRule:
    name: str
    enabled: bool
    priority: int
    match: Match
    action: OverrideAction
    set_values: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TestCase:
    test_type: str
    band: str
    standard: str
    channel: int
    center_freq_mhz: float
    bw_mhz: int
    instrument: Dict[str, Any]
    tags: Dict[str, Any] = field(default_factory=dict)
    key: str = ""
