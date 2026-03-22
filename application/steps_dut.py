# application/steps_dut.py
from __future__ import annotations
from typing import Any, Dict

from domain.steps import CaseContext, StepResult

class DutConfigureStep:
    name = "DUT_CONFIG"

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = dict(cfg)

    def run(self, ctx: CaseContext, dut) -> StepResult:
        try:
            dut.apply_rf_config(self.cfg)
            ctx.values["dut_cfg_applied"] = dict(self.cfg)
            return StepResult(step_name=self.name, status="OK", data=dict(self.cfg))
        except Exception as e:
            return StepResult(step_name=self.name, status="ERROR", message=str(e))