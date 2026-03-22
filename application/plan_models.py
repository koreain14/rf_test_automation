from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class PlanFilter:
    band: str = ""
    standard: str = ""
    phy_mode: str = ""
    bandwidth_mhz: Optional[int] = None
    channel_from: Optional[int] = None
    channel_to: Optional[int] = None
    test_type: str = ""
    enabled_state: str = "ALL"
    search_text: str = ""

    def to_filter_dict(self) -> dict:
        out: dict = {}
        if self.band:
            out["band"] = self.band
        if self.standard:
            out["standard"] = self.standard
        if self.phy_mode:
            out["phy_mode"] = self.phy_mode
        if self.bandwidth_mhz is not None:
            out["bw_mhz"] = self.bandwidth_mhz
        if self.channel_from is not None:
            out["channel_from"] = self.channel_from
        if self.channel_to is not None:
            out["channel_to"] = self.channel_to
        if self.test_type:
            out["test_type"] = self.test_type
        if self.enabled_state and self.enabled_state.upper() != "ALL":
            out["enabled_state"] = self.enabled_state
        if self.search_text:
            out["search_text"] = self.search_text
        return out


@dataclass(frozen=True)
class PlanGroupSummary:
    band: str
    standard: str
    bandwidth_mhz: int
    test_type: str
    total_count: int
    enabled_count: int = 0
    disabled_count: int = 0


@dataclass(frozen=True)
class ExecutionPolicy:
    type: str = "FILTER_BASED"
    exclude_disabled: bool = True
    exclude_excluded: bool = True


@dataclass(frozen=True)
class OrderingPolicy:
    order_by: tuple[str, ...] = ("band", "standard", "channel")
    test_priority: tuple[str, ...] = ("PSD", "OBW", "SP", "RX")



@dataclass(frozen=True)
class PlanSortSpec:
    field: str
    direction: str = "asc"

    def normalized_direction(self) -> str:
        return "desc" if str(self.direction or "asc").lower() == "desc" else "asc"


@dataclass(frozen=True)
class PlanQuery:
    filters: PlanFilter = field(default_factory=PlanFilter)
    sort: tuple[PlanSortSpec, ...] = field(default_factory=tuple)
    page: int = 1
    page_size: int = 200
    policy: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanQueryResult:
    query: PlanQuery
    rows: list[dict[str, Any]]
    total: int
    summary: list[PlanGroupSummary]
    runnable_case_keys: list[str]
    start_index: int = 0
    end_index: int = 0

    def to_page_dict(self) -> dict[str, Any]:
        return {
            "page": self.query.page,
            "page_size": self.query.page_size,
            "total": self.total,
            "rows": list(self.rows),
            "start_index": self.start_index,
            "end_index": self.end_index,
        }
