# application/runner_step.py
from __future__ import annotations
from typing import Callable, Iterable, List, Optional, Tuple

from domain.models import TestCase
from domain.steps import CaseContext, StepResult
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

        steps = self.procedures.get_steps(case.test_type)
        for step in steps:
            r: StepResult = step.run(ctx, inst)
            self.sink.write(result_id, r)

            if r.status == "ERROR":
                ctx.values["verdict"] = "ERROR"
                break

        return ctx.values  # ✅ verdict/margin/measured 등 담겨있음

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
                    # DUT 설정 실패면 해당 그룹은 진행 불가 → 다음으로 넘어갈지/중단할지 정책 선택
                    # MVP는 중단 대신 "ERROR로 계속"도 가능하지만, 여기선 중단이 안전
                    break

                prev_key = cur_key

            verdict = self.run_case(case, inst)

            count += 1
            if on_progress and (count % 20 == 0):
                on_progress(count, verdict)