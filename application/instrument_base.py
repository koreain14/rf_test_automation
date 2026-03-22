from __future__ import annotations

from typing import Any, Dict, Protocol


class MeasurementInstrument(Protocol):
    def configure(self, settings: Dict[str, Any]) -> None:
        ...

    def acquire_trace(self) -> Dict[str, Any]:
        ...
