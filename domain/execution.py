from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RunContext:
    run_id: str
    project_id: str
    preset_id: str = ""

    operator: str = ""
    dut_name: str = ""
    dut_model: str = ""
    notes: str = ""

    dry_run: bool = False

    analyzer_resource: Optional[str] = None
    switchbox_resource: Optional[str] = None
    power_supply_resource: Optional[str] = None


@dataclass
class MeasurementStep:
    step_id: str
    run_id: str
    case_id: str

    technology: str
    test_type: str
    step_type: str
    order_index: int
    name: str

    ruleset_id: str = ""
    band: str = ""
    standard: str = ""
    phy_mode: str = ""

    bandwidth_mhz: int = 0
    channel: int = 0
    frequency_mhz: float = 0.0

    instrument_profile_name: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    required_capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepExecutionResult:
    step_id: str
    status: str
    measured_value: Optional[float] = None
    unit: str = ""
    limit_value: Optional[float] = None
    margin: Optional[float] = None
    message: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)
