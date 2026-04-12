from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Sequence

from application.preset_model import PresetModel
from application.preset_validators.base_validator import BasePresetExtensionValidator
from application.preset_validators.wlan_validator import WlanPresetValidator

ValidatorFactory = Callable[[], BasePresetExtensionValidator]


class PresetValidatorRegistry:
    """Registry for technology-specific preset extension validators.

    This registry is intentionally lightweight so it can be introduced as an
    additive patch without disturbing existing validation flow. The base
    ``PresetValidator`` remains the public entry-point; the registry only
    determines which extension validators should be invoked.
    """

    def __init__(self) -> None:
        self._validator_factories: Dict[str, ValidatorFactory] = {}
        self.register_default_validators()

    def register_validator(self, tech_id: str, factory: ValidatorFactory) -> None:
        normalized = self._normalize_tech_id(tech_id)
        if not normalized:
            raise ValueError("tech_id is required")
        self._validator_factories[normalized] = factory

    def get_validator(self, tech_id: str) -> Optional[BasePresetExtensionValidator]:
        normalized = self._normalize_tech_id(tech_id)
        factory = self._validator_factories.get(normalized)
        if factory is None:
            return None
        return factory()

    def registered_tech_ids(self) -> Sequence[str]:
        return tuple(sorted(self._validator_factories.keys()))

    def resolve_validators(self, model: PresetModel) -> List[BasePresetExtensionValidator]:
        validators: List[BasePresetExtensionValidator] = []
        seen: set[str] = set()
        for tech_id in self.infer_tech_ids(model):
            normalized = self._normalize_tech_id(tech_id)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            validator = self.get_validator(normalized)
            if validator is not None:
                validators.append(validator)
        return validators

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

    def register_default_validators(self) -> None:
        if "WLAN" not in self._validator_factories:
            self.register_validator("WLAN", WlanPresetValidator)

    @staticmethod
    def _normalize_tech_id(value: str) -> str:
        return str(value or "").strip().upper()


__all__ = [
    "PresetValidatorRegistry",
    "ValidatorFactory",
]
