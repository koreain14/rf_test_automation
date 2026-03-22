from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from application.device_models import DeviceInfo


class DeviceRegistry:
    def __init__(self, path: Path):
        self.path = path

    def _read_json(self) -> dict:
        if not self.path.exists():
            return {"devices": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"devices": []}

    def _write_json(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_devices(self) -> List[DeviceInfo]:
        raw = self._read_json()
        out: List[DeviceInfo] = []
        for item in raw.get("devices", []):
            if not isinstance(item, dict):
                continue
            out.append(DeviceInfo(
                name=str(item.get("name", "")),
                type=str(item.get("type", "")),
                driver=str(item.get("driver", "")),
                resource=str(item.get("resource", "")),
                enabled=bool(item.get("enabled", True)),
                description=str(item.get("description", "")),
                serial_number=str(item.get("serial_number", "")),
                options=dict(item.get("options", {}) or {}),
                ports=list(item.get("ports", []) or []),
            ))
        return out

    def get_device(self, name: str) -> Optional[DeviceInfo]:
        for d in self.list_devices():
            if d.name == name:
                return d
        return None

    def upsert_device(self, device: DeviceInfo) -> None:
        devices = self.list_devices()
        replaced = False
        for i, d in enumerate(devices):
            if d.name == device.name:
                devices[i] = device
                replaced = True
                break
        if not replaced:
            devices.append(device)
        self._write_json({"devices": [asdict(d) for d in devices]})

    def remove_device(self, name: str) -> None:
        devices = [d for d in self.list_devices() if d.name != name]
        self._write_json({"devices": [asdict(d) for d in devices]})

    def list_devices_by_type(self, device_type: str) -> List[DeviceInfo]:
        return [d for d in self.list_devices() if d.type == device_type]
