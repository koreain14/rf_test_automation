import random
from typing import Any, Dict

class DummyInstrument:
    def __init__(self):
        self._settings = {}

    def configure(self, settings: Dict[str, Any]) -> None:
        self._settings = dict(settings)

    def acquire_trace(self) -> Dict[str, Any]:
        # trace를 흉내: 파워 레벨/노이즈 등
        return {
            "trace": [random.uniform(-80, -20) for _ in range(401)],
            "settings": dict(self._settings),
        }