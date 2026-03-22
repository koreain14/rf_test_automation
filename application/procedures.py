from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from domain.steps import CaseContext, InstrumentSession, Step, StepResult
from application.steps_common import (
    AcquireTraceStep,
    ComputeMetricsStep,
    ConfigureInstrumentStep,
    JudgeStep,
)


class BaseProcedure:
    """
    시험 절차의 공통 골격.

    현재 V10.11에서는 기존 step 기반 실행을 유지하면서도,
    절차 단위 확장이 가능하도록 lifecycle 을 명시적으로 분리한다.

    향후 확장 포인트:
    - test_type 별 precheck 강화
    - setup/acquire/compute/evaluate 커스터마이징
    - artifact 수집
    - retry / timeout / cleanup 정책
    """

    name = "BASE"

    def precheck(self, ctx: CaseContext, inst: InstrumentSession) -> Optional[StepResult]:
        return None

    def setup_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        return [ConfigureInstrumentStep()]

    def acquire_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        return [AcquireTraceStep()]

    def compute_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        return [ComputeMetricsStep()]

    def evaluate_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        return [JudgeStep()]

    def teardown(self, ctx: CaseContext, inst: InstrumentSession) -> Optional[StepResult]:
        return None

    def _run_phase(
        self,
        *,
        phase_name: str,
        ctx: CaseContext,
        inst: InstrumentSession,
        steps: List[Step],
        sink,
        result_id: str,
    ) -> Optional[StepResult]:
        for step in steps:
            r: StepResult = step.run(ctx, inst)
            sink.write(result_id, r)
            if r.status == "ERROR":
                ctx.values["verdict"] = "ERROR"
                ctx.values.setdefault("procedure_error_phase", phase_name)
                return r
        return None

    def execute(self, ctx: CaseContext, inst: InstrumentSession, sink, result_id: str) -> dict:
        pre = self.precheck(ctx, inst)
        if pre is not None:
            sink.write(result_id, pre)
            if pre.status == "ERROR":
                ctx.values["verdict"] = "ERROR"
                ctx.values.setdefault("procedure_error_phase", "precheck")
                return ctx.values

        for phase_name, provider in (
            ("setup", self.setup_steps),
            ("acquire", self.acquire_steps),
            ("compute", self.compute_steps),
            ("evaluate", self.evaluate_steps),
        ):
            failed = self._run_phase(
                phase_name=phase_name,
                ctx=ctx,
                inst=inst,
                steps=list(provider(ctx, inst)),
                sink=sink,
                result_id=result_id,
            )
            if failed is not None:
                return ctx.values

        td = self.teardown(ctx, inst)
        if td is not None:
            sink.write(result_id, td)
            if td.status == "ERROR":
                ctx.values["verdict"] = "ERROR"
                ctx.values.setdefault("procedure_error_phase", "teardown")
        return ctx.values


class SpectrumProcedure(BaseProcedure):
    """기본 analyzer trace 기반 절차."""

    name = "SPECTRUM_BASE"

    def precheck(self, ctx: CaseContext, inst: InstrumentSession) -> Optional[StepResult]:
        missing = []
        if not hasattr(inst, "configure"):
            missing.append("configure")
        if not hasattr(inst, "acquire_trace"):
            missing.append("acquire_trace")
        if missing:
            return StepResult(
                step_name="PREFLIGHT",
                status="ERROR",
                message=(
                    f"Instrument '{type(inst).__name__}' missing required capabilities: {', '.join(missing)}"
                ),
                data={"procedure": self.name, "missing_capabilities": missing},
            )
        return StepResult(
            step_name="PREFLIGHT",
            status="OK",
            data={"procedure": self.name, "test_type": ctx.case.test_type},
        )


class PsdProcedure(SpectrumProcedure):
    name = "PSD"


class ObwProcedure(SpectrumProcedure):
    name = "OBW"


class SpuriousProcedure(SpectrumProcedure):
    name = "SP"


class RxProcedure(SpectrumProcedure):
    name = "RX"


@dataclass
class ProcedureSpec:
    test_type: str
    procedure: BaseProcedure


class ProcedureRegistry:
    """
    V10.11 절차 레지스트리.

    - 기존 step registry 역할 유지
    - procedure 객체를 반환할 수 있게 확장
    - 기존 run path 영향 최소화를 위해 get_steps()도 유지
    """

    def __init__(self):
        self._map: Dict[str, BaseProcedure] = {
            "PSD": PsdProcedure(),
            "OBW": ObwProcedure(),
            "SP": SpuriousProcedure(),
            "RX": RxProcedure(),
        }

    def get_procedure(self, test_type: str) -> BaseProcedure:
        if test_type not in self._map:
            raise KeyError(f"No procedure for test_type={test_type}")
        return self._map[test_type]

    def get_steps(self, test_type: str) -> List[Step]:
        # backward compatibility for legacy callers
        return [
            ConfigureInstrumentStep(),
            AcquireTraceStep(),
            ComputeMetricsStep(),
            JudgeStep(),
        ]
