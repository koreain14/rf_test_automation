from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence

from application.plan_builders.base_builder import BasePlanBuilder
from application.plan_builders.wlan_plan_builder import WlanPlanBuilder
from application.preset_model import PresetModel

BuilderFactory = Callable[[], BasePlanBuilder]


class PlanBuilderRegistry:
    """Technology-specific plan builder registry.

    The registry is intentionally additive. Existing WLAN behavior remains
    available through the default registration and callers can still fall back
    to legacy code paths if no builder is resolved.
    """

    def __init__(self) -> None:
        self._builder_factories: Dict[str, BuilderFactory] = {}
        self.register_default_builders()

    def register_builder(self, tech_id: str, factory: BuilderFactory) -> None:
        normalized = self._normalize_tech_id(tech_id)
        if not normalized:
            raise ValueError("tech_id is required")
        self._builder_factories[normalized] = factory

    def get_builder(self, tech_id: str) -> Optional[BasePlanBuilder]:
        normalized = self._normalize_tech_id(tech_id)
        factory = self._builder_factories.get(normalized)
        if factory is None:
            return None
        return factory()

    def registered_tech_ids(self) -> Sequence[str]:
        return tuple(sorted(self._builder_factories.keys()))

    def resolve_builder(self, model: PresetModel) -> Optional[BasePlanBuilder]:
        for tech_id in self.infer_tech_ids(model):
            builder = self.get_builder(tech_id)
            if builder is not None:
                return builder
        return None

    def build_steps(self, model: PresetModel) -> list[dict]:
        builder = self.resolve_builder(model)
        if builder is None:
            return []
        return builder.build_steps(model)

    def infer_tech_ids(self, model: PresetModel) -> List[str]:
        candidates: List[str] = []

        ruleset_id = str(getattr(model, "ruleset_id", "") or "").strip()
        selection = getattr(model, "selection", None)
        standard = str(getattr(selection, "standard", "") or "").strip()
        metadata = dict(getattr(selection, "metadata", {}) or {}) if selection is not None else {}

        explicit = metadata.get("tech_id") or metadata.get("technology")
        if explicit:
            candidates.append(str(explicit))

        upper_ruleset = ruleset_id.upper()
        upper_standard = standard.upper()

        if "WLAN" in upper_ruleset or upper_standard.startswith("802.11"):
            candidates.append("WLAN")
        if "BT" in upper_ruleset or "BLUETOOTH" in upper_ruleset or upper_standard.startswith("BT"):
            candidates.append("BT")
        if "UWB" in upper_ruleset or upper_standard.startswith("UWB"):
            candidates.append("UWB")
        if "LTE" in upper_ruleset or upper_standard.startswith("LTE"):
            candidates.append("LTE")
        if "NR" in upper_ruleset or upper_standard.startswith("NR") or upper_standard.startswith("5G"):
            candidates.append("NR")

        ordered: List[str] = []
        seen: set[str] = set()
        for tech_id in candidates:
            normalized = self._normalize_tech_id(tech_id)
            if normalized and normalized not in seen:
                ordered.append(normalized)
                seen.add(normalized)
        return ordered

    def register_default_builders(self) -> None:
        if "WLAN" not in self._builder_factories:
            self.register_builder("WLAN", WlanPlanBuilder)

    @staticmethod
    def _normalize_tech_id(value: str) -> str:
        return str(value or "").strip().upper()


__all__ = [
    "PlanBuilderRegistry",
    "BuilderFactory",
]
