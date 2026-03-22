from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_TEST_ORDER = ["PSD", "OBW", "SP", "RX"]


@dataclass
class ChannelSelectionModel:
    policy: str = "CUSTOM_LIST"
    channels: list[int] = field(default_factory=list)
    grouping: str = ""
    groups: list[str] = field(default_factory=list)
    representatives_override: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPolicyModel:
    type: str = "CHANNEL_CENTRIC"
    test_order: list[str] = field(default_factory=lambda: list(DEFAULT_TEST_ORDER))
    include_bw_in_group: bool = True


@dataclass
class WlanModeRowModel:
    """Single WLAN standard/PHY/BW selection row used by the WLAN expansion editor."""

    standard: str = ""
    phy_mode: str = ""
    bandwidths_mhz: list[int] = field(default_factory=list)


@dataclass
class WlanChannelRowModel:
    """Per-bandwidth WLAN channel mapping row."""

    bandwidth_mhz: int = 20
    channels: list[int] = field(default_factory=list)
    frequencies_mhz: list[float] = field(default_factory=list)


@dataclass
class WlanExpansionModel:
    mode_plan: list[WlanModeRowModel] = field(default_factory=list)
    channel_plan: list[WlanChannelRowModel] = field(default_factory=list)


@dataclass
class PresetSelectionModel:
    band: str = ""
    standard: str = ""
    plan_mode: str = "DEMO"
    test_types: list[str] = field(default_factory=list)
    bandwidth_mhz: list[int] = field(default_factory=list)
    channels: ChannelSelectionModel = field(default_factory=ChannelSelectionModel)
    execution_policy: ExecutionPolicyModel = field(default_factory=ExecutionPolicyModel)
    instrument_profile_by_test: dict[str, str] = field(default_factory=dict)
    device_class: str = ""
    defaults: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    wlan_expansion: WlanExpansionModel | None = None


@dataclass
class PresetModel:
    name: str
    ruleset_id: str
    ruleset_version: str
    selection: PresetSelectionModel
    description: str = ""
    schema_version: int = 2
    source_path: str = ""
    is_builtin: bool = False
