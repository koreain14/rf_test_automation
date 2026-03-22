from __future__ import annotations

from typing import Any, Optional


class PyVisaDeviceBase:
    def __init__(self, resource: str, timeout_ms: int = 10000):
        self.resource = resource
        self.timeout_ms = timeout_ms
        self.rm: Optional[Any] = None
        self.inst: Optional[Any] = None
        self._last_connect_error: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self.inst is not None

    @property
    def last_connect_error(self) -> Optional[str]:
        return self._last_connect_error

    def connect(self) -> None:
        self._last_connect_error = None
        try:
            import pyvisa  # type: ignore
            self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(self.resource)
            try:
                self.inst.timeout = self.timeout_ms
            except Exception:
                pass
        except Exception as e:
            self.inst = None
            self._last_connect_error = str(e)

    def disconnect(self) -> None:
        try:
            if self.inst is not None and hasattr(self.inst, "close"):
                self.inst.close()
        except Exception:
            pass
        try:
            if self.rm is not None and hasattr(self.rm, "close"):
                self.rm.close()
        except Exception:
            pass
        self.inst = None
        self.rm = None

    def write(self, cmd: str) -> None:
        if not self.inst:
            raise RuntimeError(self._last_connect_error or "Device not connected")
        self.inst.write(cmd)

    def query(self, cmd: str) -> str:
        if not self.inst:
            raise RuntimeError(self._last_connect_error or "Device not connected")
        return str(self.inst.query(cmd))

    def query_idn(self) -> str:
        return self.query("*IDN?")
