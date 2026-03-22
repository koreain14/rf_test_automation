from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DeviceInfo:
    name: str
    type: str
    driver: str
    resource: str
    enabled: bool = True
    description: str = ""
    serial_number: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
    ports: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class EquipmentProfile:
    name: str
    analyzer: Optional[str] = None
    turntable: Optional[str] = None
    mast: Optional[str] = None
    switchbox: Optional[str] = None
    power_supply: Optional[str] = None


DEVICE_TYPES = [
    "analyzer",
    "turntable",
    "mast",
    "switchbox",
    "power_supply",
]

DRIVER_CHOICES = [
    "rs_fsw",
    "rs_esw",
    "keysight_n9030",
    "keysight_n9020",
    "innco_co3000",
    "innco_mast",
    "generic_switch",
    "keysight_e3632a",
]
