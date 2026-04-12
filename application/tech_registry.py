from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

from application.plan_builder_registry import PlanBuilderRegistry
from application.preset_model import PresetModel
from application.preset_validator_registry import PresetValidatorRegistry

EditorFactory = Callable[..., Any]


def _build_wlan_editor(*args, **kwargs):
    from ui.preset_editors import WlanExpansionEditor
    return WlanExpansionEditor(*args, **kwargs)


@dataclass(frozen=True)
class TechDescriptor:
    tech_id: str
    display_name: str
    editor_factory: Optional[EditorFactory] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)


class TechRegistry:
    """Aggregates tech-level descriptor metadata and registry lookups.

    The validator and builder registries remain the source of truth for their
    respective responsibilities. This registry simply provides a technology-
    centric lookup facade.
    """

    def __init__(
        self,
        validator_registry: Optional[PresetValidatorRegistry] = None,
        builder_registry: Optional[PlanBuilderRegistry] = None,
    ) -> None:
        self._validator_registry = validator_registry or PresetValidatorRegistry()
        self._builder_registry = builder_registry or PlanBuilderRegistry()
        self._descriptors: Dict[str, TechDescriptor] = {}
        self.register_default_descriptors()

    def register_descriptor(self, descriptor: TechDescriptor) -> None:
        tech_id = self._normalize_tech_id(descriptor.tech_id)
        if not tech_id:
            raise ValueError("descriptor.tech_id is required")
        self._descriptors[tech_id] = TechDescriptor(
            tech_id=tech_id,
            display_name=str(descriptor.display_name or tech_id),
            editor_factory=descriptor.editor_factory,
            capabilities=dict(descriptor.capabilities or {}),
        )

    def get_descriptor(self, tech_id: str) -> Optional[TechDescriptor]:
        return self._descriptors.get(self._normalize_tech_id(tech_id))

    def registered_tech_ids(self) -> Sequence[str]:
        tech_ids = set(self._descriptors.keys())
        tech_ids.update(self._validator_registry.registered_tech_ids())
        tech_ids.update(self._builder_registry.registered_tech_ids())
        return tuple(sorted(tech_ids))

    def infer_tech_ids(self, model: PresetModel) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for source in (
            self._validator_registry.infer_tech_ids(model),
            self._builder_registry.infer_tech_ids(model),
        ):
            for tech_id in source:
                normalized = self._normalize_tech_id(tech_id)
                if normalized and normalized not in seen:
                    ordered.append(normalized)
                    seen.add(normalized)
        return ordered

    def resolve_descriptor(self, model: PresetModel) -> Optional[TechDescriptor]:
        for tech_id in self.infer_tech_ids(model):
            descriptor = self.get_descriptor(tech_id)
            if descriptor is not None:
                return descriptor
        return None

    def get_validator_for_tech(self, tech_id: str):
        return self._validator_registry.get_validator(tech_id)

    def get_builder_for_tech(self, tech_id: str):
        return self._builder_registry.get_builder(tech_id)

    def get_editor_factory_for_tech(self, tech_id: str) -> Optional[EditorFactory]:
        descriptor = self.get_descriptor(tech_id)
        return descriptor.editor_factory if descriptor is not None else None

    def get_capabilities_for_tech(self, tech_id: str) -> Dict[str, Any]:
        descriptor = self.get_descriptor(tech_id)
        return dict(descriptor.capabilities or {}) if descriptor is not None else {}

    def get_validator_for_model(self, model: PresetModel):
        for tech_id in self.infer_tech_ids(model):
            validator = self.get_validator_for_tech(tech_id)
            if validator is not None:
                return validator
        return None

    def get_builder_for_model(self, model: PresetModel):
        for tech_id in self.infer_tech_ids(model):
            builder = self.get_builder_for_tech(tech_id)
            if builder is not None:
                return builder
        return None

    def get_editor_factory_for_model(self, model: PresetModel) -> Optional[EditorFactory]:
        descriptor = self.resolve_descriptor(model)
        return descriptor.editor_factory if descriptor is not None else None

    def register_default_descriptors(self) -> None:
        if self.get_descriptor("WLAN") is None:
            self.register_descriptor(
                TechDescriptor(
                    tech_id="WLAN",
                    display_name="WLAN",
                    editor_factory=_build_wlan_editor,
                    capabilities={
                        "supports_preview_builder": True,
                        "supports_extension_validator": True,
                        "supports_editor_factory": True,
                        "editor_factory_name": "WlanExpansionEditor",
                    },
                )
            )

    @staticmethod
    def _normalize_tech_id(value: str) -> str:
        return str(value or "").strip().upper()


__all__ = [
    "EditorFactory",
    "TechDescriptor",
    "TechRegistry",
]
