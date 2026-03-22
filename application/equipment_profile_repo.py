from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from application.device_models import EquipmentProfile


class EquipmentProfileRepo:
    def __init__(self, path: Path):
        self.path = path

    def _read_json(self) -> dict:
        if not self.path.exists():
            return {"profiles": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"profiles": []}

    def _write_json(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_profiles(self) -> List[EquipmentProfile]:
        raw = self._read_json()
        out: List[EquipmentProfile] = []
        for item in raw.get("profiles", []):
            if not isinstance(item, dict):
                continue
            out.append(EquipmentProfile(
                name=str(item.get("name", "")),
                analyzer=item.get("analyzer"),
                turntable=item.get("turntable"),
                mast=item.get("mast"),
                switchbox=item.get("switchbox"),
                power_supply=item.get("power_supply"),
            ))
        return out

    def get_profile(self, name: str) -> Optional[EquipmentProfile]:
        for p in self.list_profiles():
            if p.name == name:
                return p
        return None

    def upsert_profile(self, profile: EquipmentProfile) -> None:
        profiles = self.list_profiles()
        replaced = False
        for i, p in enumerate(profiles):
            if p.name == profile.name:
                profiles[i] = profile
                replaced = True
                break
        if not replaced:
            profiles.append(profile)
        self._write_json({"profiles": [asdict(p) for p in profiles]})

    def remove_profile(self, name: str) -> None:
        profiles = [p for p in self.list_profiles() if p.name != name]
        self._write_json({"profiles": [asdict(p) for p in profiles]})
