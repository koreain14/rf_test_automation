from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import logging

log = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    analyzer: Any = None
    turntable: Any = None
    mast: Any = None
    switchbox: Any = None
    power_supply: Any = None

    def get(self, name: str, default=None):
        return getattr(self, name, default)

    def has(self, name: str) -> bool:
        return getattr(self, name, None) is not None

    def summary(self) -> dict:
        return {
            name: (type(getattr(self, name)).__name__ if getattr(self, name) is not None else None)
            for name in ("analyzer", "turntable", "mast", "switchbox", "power_supply")
        }

    def cleanup(self, power_output_off: bool = False) -> None:
        power_supply = self.power_supply
        if power_output_off and power_supply is not None and hasattr(power_supply, "output_off"):
            try:
                power_supply.output_off()
            except Exception:
                log.warning("power off failed during cleanup", exc_info=True)

        for attr in ("analyzer", "turntable", "mast", "switchbox", "power_supply"):
            dev = getattr(self, attr, None)
            if dev is not None and hasattr(dev, "disconnect"):
                try:
                    dev.disconnect()
                except Exception:
                    log.warning("disconnect failed during cleanup: %s", attr, exc_info=True)


EquipmentSession = ExecutionContext
