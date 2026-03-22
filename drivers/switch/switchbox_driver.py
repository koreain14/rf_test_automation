from __future__ import annotations

from typing import Any, Dict, List

from drivers.common.pyvisa_device_base import PyVisaDeviceBase


class SwitchBoxDriver(PyVisaDeviceBase):
    def __init__(self, resource: str, ports: List[Dict[str, Any]] | None = None, timeout_ms: int = 5000):
        super().__init__(resource, timeout_ms)
        self.ports = list(ports or [])

    def list_paths(self) -> List[str]:
        return [str(p.get("name", "")) for p in self.ports if p.get("name")]

    def select_path(self, path_name: str) -> None:
        port = next((p for p in self.ports if str(p.get("name")) == path_name), None)
        if not port:
            raise ValueError(f"Unknown path: {path_name}")
        command = str(port.get("command", "")).strip()
        if not command:
            raise ValueError(f"No command defined for path: {path_name}")
        self.write(command)
