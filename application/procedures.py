from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Dict, List, Optional

from application.test_type_symbols import normalize_test_type_symbol
from domain.steps import CaseContext, InstrumentSession, Step, StepResult
from application.steps_common import (
    AcquireTraceStep,
    ComputeMetricsStep,
    ConfigureInstrumentStep,
    JudgeStep,
)
from application.measurements.keysight_obw_helper import (
    detect_keysight_xseries_analyzer,
    measure_obw_keysight,
    mock_obw_measurement,
)

log = logging.getLogger(__name__)


class BaseProcedure:
    """시험 절차의 공통 골격."""

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

    def _run_phase(self, *, phase_name: str, ctx: CaseContext, inst: InstrumentSession, steps: List[Step], sink, result_id: str) -> Optional[StepResult]:
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

        for phase_name, provider in (("setup", self.setup_steps), ("acquire", self.acquire_steps), ("compute", self.compute_steps), ("evaluate", self.evaluate_steps)):
            failed = self._run_phase(phase_name=phase_name, ctx=ctx, inst=inst, steps=list(provider(ctx, inst)), sink=sink, result_id=result_id)
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
                message=(f"Instrument '{type(inst).__name__}' missing required capabilities: {', '.join(missing)}"),
                data={"procedure": self.name, "missing_capabilities": missing},
            )
        return StepResult(step_name="PREFLIGHT", status="OK", data={"procedure": self.name, "test_type": ctx.case.test_type})


class PsdProcedure(SpectrumProcedure):
    name = "PSD"


class ObwMeasureStep:
    name = "OBW_MEASURE"

    def run(self, ctx: CaseContext, inst) -> StepResult:
        detection = detect_keysight_xseries_analyzer(inst)
        use_real = bool(detection.get("usable"))
        backend = "real" if use_real else "mock"
        reason = str(detection.get("reason") or "unknown")
        idn = str(detection.get("idn") or "")
        source_class = str(detection.get("source_class") or type(inst).__name__)
        log.info(
            "obw backend selected | case=%s backend=%s reason=%s source_class=%s idn=%s",
            getattr(ctx.case, "key", ""), backend, reason, source_class, idn,
        )

        try:
            result = measure_obw_keysight(inst, ctx.case) if use_real else mock_obw_measurement(ctx.case)
        except Exception as exc:
            ctx.values["verdict"] = "ERROR"
            ctx.values["measurement_source"] = backend
            ctx.values["backend_reason"] = reason
            ctx.values["error_message"] = str(exc)
            return StepResult(
                step_name=self.name,
                status="ERROR",
                message=str(exc),
                data={
                    "measurement_source": backend,
                    "backend_reason": reason,
                    "backend_idn": idn,
                    "source_class": source_class,
                },
            )

        ctx.values["measured_value"] = result["measured_value"]
        ctx.values["limit_value"] = result["limit_value"]
        ctx.values["margin_db"] = result["margin_db"]
        ctx.values["measurement_unit"] = result.get("measurement_unit", "MHz")
        ctx.values["measurement_source"] = result.get("measurement_source", backend)
        ctx.values["backend_reason"] = result.get("backend_reason", reason)
        if result.get("backend_idn"):
            ctx.values["backend_idn"] = result.get("backend_idn")
        if result.get("error_message"):
            ctx.values["error_message"] = result.get("error_message")

        return StepResult(
            step_name=self.name,
            status="OK",
            data={
                "measured_value": result["measured_value"],
                "limit_value": result["limit_value"],
                "margin_db": result["margin_db"],
                "measurement_unit": result.get("measurement_unit", "MHz"),
                "measurement_source": result.get("measurement_source", backend),
                "backend_reason": result.get("backend_reason", reason),
                "backend_idn": result.get("backend_idn", idn),
            },
        )


class ObwProcedure(SpectrumProcedure):
    name = "OBW"

    def precheck(self, ctx: CaseContext, inst: InstrumentSession) -> Optional[StepResult]:
        detection = detect_keysight_xseries_analyzer(inst)
        backend = "real" if detection.get("usable") else "mock"
        return StepResult(
            step_name="PREFLIGHT",
            status="OK",
            data={
                "procedure": self.name,
                "test_type": ctx.case.test_type,
                "measurement_source": backend,
                "backend_reason": detection.get("reason", "unknown"),
                "backend_idn": detection.get("idn", ""),
            },
        )

    def setup_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        detection = detect_keysight_xseries_analyzer(inst)
        if detection.get("usable"):
            return [ConfigureInstrumentStep()]
        return []

    def acquire_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        return [ObwMeasureStep()]

    def compute_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        return []


class SpuriousProcedure(SpectrumProcedure):
    name = "SP"


class RxProcedure(SpectrumProcedure):
    name = "RX"


@dataclass
class ProcedureSpec:
    test_type: str
    procedure: BaseProcedure


class ProcedureRegistry:
    def __init__(self):
        self._map: Dict[str, BaseProcedure] = {
            "PSD": PsdProcedure(),
            "OBW": ObwProcedure(),
            "SP": SpuriousProcedure(),
            "RX": RxProcedure(),
        }

    def _normalize(self, test_type: str) -> str:
        return normalize_test_type_symbol(test_type)

    def get_procedure(self, test_type: str) -> BaseProcedure:
        key = self._normalize(test_type)
        if key not in self._map:
            raise KeyError(f"No procedure for test_type={test_type}")
        return self._map[key]

    def get_steps(self, test_type: str) -> List[Step]:
        return [ConfigureInstrumentStep(), AcquireTraceStep(), ComputeMetricsStep(), JudgeStep()]
