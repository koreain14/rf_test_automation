# application/runner_step.py
from __future__ import annotations
from typing import Callable, Iterable, Optional, Tuple

from domain.models import TestCase
from domain.steps import CaseContext
from application.procedures import ProcedureRegistry
from application.steps_dut import DutConfigureStep


def _dut_group_key(c: TestCase) -> Tuple:
    # DUT 변경 최소화를 위한 그룹 키
    return (c.standard, c.band, c.channel, c.bw_mhz)


class StepRunner:
    def __init__(self, procedures: ProcedureRegistry, sink):
        self.procedures = procedures
        self.sink = sink  # sink.write(result_id, StepResult)

    def run_case(self, result_id: str, case, inst) -> dict:
        ctx = CaseContext(case=case)
        procedure = self.procedures.get_procedure(case.test_type)
        ctx.values["procedure_name"] = getattr(procedure, "name", case.test_type)
        return procedure.execute(ctx, inst, self.sink, result_id)

    def run_cases(
        self,
        cases: Iterable[TestCase],
        inst,
        dut,
        should_stop: Callable[[], bool],
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        prev_key = None
        count = 0

        for case in cases:
            if should_stop():
                break

            cur_key = _dut_group_key(case)

            # ✅ 그룹 변경 시에만 DUT 설정
            if prev_key is None or cur_key != prev_key:
                ctx = CaseContext(case=case)
                dut_step = DutConfigureStep({
                    "standard": case.standard,
                    "band": case.band,
                    "channel": case.channel,
                    "bw_mhz": case.bw_mhz,
                })
                r = dut_step.run(ctx, dut)
                self.sink(case, r)
                if r.status == "ERROR":
                    break

                prev_key = cur_key

            values = self.run_case(case, inst)
            verdict = values.get("verdict", "ERROR")

            count += 1
            if on_progress and (count % 20 == 0):
                on_progress(count, verdict)
