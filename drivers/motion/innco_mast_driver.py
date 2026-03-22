from __future__ import annotations


class INNCOMastDriver:
    def __init__(self, resource: str, options: dict | None = None):
        self.resource = resource
        self.options = dict(options or {})
        self.connected = False
        self._height_cm = 0.0
        self._polarization = "Horizontal"

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def move_to(self, height_cm: float) -> None:
        if not self.connected:
            raise RuntimeError("Mast not connected")
        self._height_cm = float(height_cm)

    def get_position(self) -> float:
        return float(self._height_cm)

    def set_polarization(self, value: str) -> None:
        if not self.connected:
            raise RuntimeError("Mast not connected")
        value = str(value).strip().title()
        if value not in ("Horizontal", "Vertical"):
            raise ValueError("Polarization must be 'Horizontal' or 'Vertical'")
        self._polarization = value

    def get_polarization(self) -> str:
        return str(self._polarization)
