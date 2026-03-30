from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MeasurementProfileDocument:
    name: str
    version: int
    base: str | None = None
    description: str = ""
    common: dict[str, Any] = field(default_factory=dict)
    measurements: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "version": int(self.version),
            "common": dict(self.common or {}),
            "measurements": {str(k): dict(v or {}) for k, v in (self.measurements or {}).items()},
        }
        if self.base:
            data["base"] = self.base
        if self.description:
            data["description"] = self.description
        if self.meta:
            data["meta"] = dict(self.meta)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: Path | None = None) -> "MeasurementProfileDocument":
        return cls(
            name=str(data.get("name", "") or ""),
            version=int(data.get("version", 1) or 1),
            base=(str(data.get("base", "")).strip() or None),
            description=str(data.get("description", "") or ""),
            common=dict(data.get("common") or {}),
            measurements={str(k): dict(v or {}) for k, v in dict(data.get("measurements") or {}).items()},
            meta=dict(data.get("meta") or {}),
            source_path=source_path,
        )
