from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


_FACTOR_FIELDS = (
    "cable_loss_db",
    "attenuator_db",
    "dut_cable_loss_db",
    "switchbox_loss_db",
    "divider_loss_db",
    "external_gain_db",
)


@dataclass
class CorrectionFactorSet:
    cable_loss_db: float = 0.0
    attenuator_db: float = 0.0
    dut_cable_loss_db: float = 0.0
    switchbox_loss_db: float = 0.0
    divider_loss_db: float = 0.0
    external_gain_db: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name, 0.0) or 0.0) for name in _FACTOR_FIELDS}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CorrectionFactorSet":
        payload = dict(data or {})
        values: Dict[str, float] = {}
        for name in _FACTOR_FIELDS:
            try:
                values[name] = float(payload.get(name, 0.0) or 0.0)
            except Exception:
                values[name] = 0.0
        return cls(**values)


@dataclass
class CorrectionProfileDocument:
    name: str
    mode: str
    description: str = ""
    factors: CorrectionFactorSet = field(default_factory=CorrectionFactorSet)
    ports: dict[str, CorrectionFactorSet] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    def normalized_mode(self) -> str:
        value = str(self.mode or "DIRECT").strip().upper()
        return value if value in {"DIRECT", "SWITCH"} else "DIRECT"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "mode": self.normalized_mode(),
        }
        if self.description:
            data["description"] = self.description
        if self.normalized_mode() == "DIRECT":
            data["factors"] = self.factors.to_dict()
        else:
            data["ports"] = {str(name): factors.to_dict() for name, factors in dict(self.ports or {}).items()}
        if self.meta:
            data["meta"] = dict(self.meta)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: Path | None = None) -> "CorrectionProfileDocument":
        payload = dict(data or {})
        mode = str(payload.get("mode", "DIRECT") or "DIRECT").strip().upper()
        ports_raw = dict(payload.get("ports") or {})
        return cls(
            name=str(payload.get("name", "") or ""),
            mode=mode if mode in {"DIRECT", "SWITCH"} else "DIRECT",
            description=str(payload.get("description", "") or ""),
            factors=CorrectionFactorSet.from_dict(payload.get("factors") or {}),
            ports={str(name): CorrectionFactorSet.from_dict(item) for name, item in ports_raw.items()},
            meta=dict(payload.get("meta") or {}),
            source_path=source_path,
        )


__all__ = [
    "CorrectionFactorSet",
    "CorrectionProfileDocument",
]
