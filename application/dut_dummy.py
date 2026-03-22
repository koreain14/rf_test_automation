# application/dut_dummy.py
from __future__ import annotations
from typing import Any, Dict

class DummyDUT:
    def __init__(self):
        self._last_cfg: Dict[str, Any] = {}

    def apply_rf_config(self, cfg: Dict[str, Any]) -> None:
        # 실제로는: DUT에 mode/channel/bw 세팅 (ADB, UART, Ethernet, vendor API 등)
        # 지금은 캐시만 갱신
        self._last_cfg = dict(cfg)