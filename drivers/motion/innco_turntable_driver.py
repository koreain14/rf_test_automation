from __future__ import annotations


class INNCOTurntableDriver:
    def __init__(self, resource: str, options: dict | None = None):
        self.resource = resource
        self.options = dict(options or {})
        self.connected = False
        self._angle_deg = 0.0

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def move_to(self, angle_deg: float) -> None:
        if not self.connected:
            raise RuntimeError("Turntable not connected")
        self._angle_deg = float(angle_deg)

    def get_position(self) -> float:
        if not self.connected:
            raise RuntimeError("Turntable not connected")
        return float(self._angle_deg)
