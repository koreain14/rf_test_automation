from __future__ import annotations

from typing import Any, Dict


class KeysightXSeriesAnalyzer:
    def __init__(self, driver):
        self.driver = driver

    def connect(self) -> None:
        if hasattr(self.driver, "connect"):
            self.driver.connect()

    def disconnect(self) -> None:
        if hasattr(self.driver, "disconnect"):
            self.driver.disconnect()

    def reset(self) -> None:
        if hasattr(self.driver, "reset"):
            self.driver.reset()

    def configure(self, settings: Dict[str, Any]) -> None:
        if hasattr(self.driver, "configure"):
            self.driver.configure(settings)

    def get_trace(self) -> Dict[str, Any]:
        if hasattr(self.driver, "get_trace"):
            return self.driver.get_trace()
        if hasattr(self.driver, "acquire_trace"):
            return self.driver.acquire_trace()
        return {"trace": [], "source": "UNSUPPORTED"}
