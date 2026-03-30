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
from application.measurement_profile_runtime import build_consumable_measurement_profile
from application.measurements.keysight_obw_helper import (
    detect_keysight_xseries_analyzer,
    measure_obw_keysight,
    mock_obw_measurement,
)
from application.measurements.keysight_psd_helper import measure_psd_keysight
from application.psd_unit_policy import PSD_CANONICAL_UNIT, build_psd_display_payload, normalize_psd_result_unit

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


class PsdMeasureStep:
    name = "PSD_MEASURE"

    @staticmethod
    def _display_unit_from_case(case) -> str:
        tags = dict(getattr(case, "tags", {}) or {})
        return normalize_psd_result_unit(tags.get("psd_result_unit")) or PSD_CANONICAL_UNIT

    @staticmethod
    def _display_unit_label(unit: str) -> str:
        return "mW/MHz" if normalize_psd_result_unit(unit) == "MW_PER_MHZ" else "dBm/MHz"

    def run(self, ctx: CaseContext, inst) -> StepResult:
        detection = detect_keysight_xseries_analyzer(inst)
        use_real = bool(detection.get("usable"))
        backend = "real" if use_real else "mock"
        reason = str(detection.get("reason") or "unknown")
        idn = str(detection.get("idn") or "")
        source_class = str(detection.get("source_class") or type(inst).__name__)
        log.info(
            "psd backend selected | case=%s backend=%s reason=%s source_class=%s idn=%s",
            getattr(ctx.case, "key", ""),
            backend,
            reason,
            source_class,
            idn,
        )

        resolved_profile = build_consumable_measurement_profile(
            test_type=getattr(ctx.case, "test_type", ""),
            resolved_profile=dict(ctx.values.get("resolved_profile") or {}),
            instrument_snapshot=dict(getattr(ctx.case, "instrument", {}) or {}),
        )
        ctx.values["resolved_profile"] = dict(resolved_profile)

        try:
            if use_real:
                result = measure_psd_keysight(inst, ctx.case, profile_settings=resolved_profile)
            else:
                settings = dict(resolved_profile or getattr(ctx.case, "instrument", {}) or {})
                if hasattr(inst, "configure"):
                    inst.configure(settings)
                trace_payload = inst.acquire_trace() if hasattr(inst, "acquire_trace") else {"trace": []}
                trace = trace_payload.get("trace", [])
                if isinstance(trace, str):
                    trace = [float(token.strip()) for token in trace.split(",") if token.strip()]
                if not trace:
                    raise RuntimeError("No trace")
                measured = max(float(x) for x in trace)
                limit = -30.0
                margin = limit - measured
                display_unit = self._display_unit_from_case(ctx.case)
                display_payload = build_psd_display_payload(
                    canonical_value_dbm_per_mhz=measured,
                    display_unit=display_unit,
                )
                display_limit_payload = build_psd_display_payload(
                    canonical_value_dbm_per_mhz=limit,
                    display_unit=display_unit,
                )
                result = {
                    "measured_value": measured,
                    "limit_value": limit,
                    "margin_db": margin,
                    "measurement_unit": "dBm/MHz",
                    "canonical_measurement_unit": self._display_unit_label(PSD_CANONICAL_UNIT),
                    "psd_result_unit": display_payload["display_unit"],
                    "psd_canonical_unit": display_payload["canonical_unit"],
                    "display_measured_value": display_payload["display_value"],
                    "display_limit_value": display_limit_payload["display_value"],
                    "display_measurement_unit": self._display_unit_label(display_payload["display_unit"]),
                    "measurement_source": "mock",
                    "backend_reason": reason,
                    "backend_idn": idn,
                    "measurement_profile_name": resolved_profile.get("profile_name", ""),
                    "measurement_profile_source": resolved_profile.get("profile_source", ""),
                    "trace_point_count": len(trace),
                    "verdict": "PASS" if margin >= 0 else "FAIL",
                }
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
                    "measurement_profile_name": resolved_profile.get("profile_name", ""),
                    "measurement_profile_source": resolved_profile.get("profile_source", ""),
                },
            )

        ctx.values["measured_value"] = result["measured_value"]
        ctx.values["limit_value"] = result["limit_value"]
        ctx.values["margin_db"] = result["margin_db"]
        ctx.values["measurement_unit"] = result.get("measurement_unit", "dBm/MHz")
        ctx.values["measurement_source"] = result.get("measurement_source", backend)
        ctx.values["backend_reason"] = result.get("backend_reason", reason)
        if result.get("backend_idn"):
            ctx.values["backend_idn"] = result.get("backend_idn")
        if result.get("error_message"):
            ctx.values["error_message"] = result.get("error_message")
        if result.get("scpi_trace_mode"):
            ctx.values["scpi_trace_mode"] = result.get("scpi_trace_mode")
        if result.get("scpi_detector"):
            ctx.values["scpi_detector"] = result.get("scpi_detector")
        if result.get("scpi_average_enabled") is not None:
            ctx.values["scpi_average_enabled"] = result.get("scpi_average_enabled")
        if result.get("scpi_avg_count") is not None:
            ctx.values["scpi_avg_count"] = result.get("scpi_avg_count")
        if result.get("trace_point_count") is not None:
            ctx.values["trace_point_count"] = result.get("trace_point_count")
        if result.get("display_measured_value") is not None:
            ctx.values["display_measured_value"] = result.get("display_measured_value")
        if result.get("display_limit_value") is not None:
            ctx.values["display_limit_value"] = result.get("display_limit_value")
        if result.get("display_measurement_unit"):
            ctx.values["display_measurement_unit"] = result.get("display_measurement_unit")
        if result.get("psd_result_unit"):
            ctx.values["psd_result_unit"] = result.get("psd_result_unit")
        if result.get("psd_canonical_unit"):
            ctx.values["psd_canonical_unit"] = result.get("psd_canonical_unit")
        ctx.values["verdict"] = result.get("verdict", "ERROR")

        return StepResult(
            step_name=self.name,
            status="OK",
            data={
                "measured_value": result["measured_value"],
                "limit_value": result["limit_value"],
                "margin_db": result["margin_db"],
                "measurement_unit": result.get("measurement_unit", "dBm/MHz"),
                "measurement_source": result.get("measurement_source", backend),
                "backend_reason": result.get("backend_reason", reason),
                "backend_idn": result.get("backend_idn", idn),
                "measurement_profile_name": resolved_profile.get("profile_name", ""),
                "measurement_profile_source": resolved_profile.get("profile_source", ""),
                "canonical_measurement_unit": result.get("canonical_measurement_unit", "dBm/MHz"),
                "psd_result_unit": result.get("psd_result_unit", ""),
                "psd_canonical_unit": result.get("psd_canonical_unit", PSD_CANONICAL_UNIT),
                "display_measured_value": result.get("display_measured_value"),
                "display_limit_value": result.get("display_limit_value"),
                "display_measurement_unit": result.get("display_measurement_unit", "dBm/MHz"),
                "trace_point_count": result.get("trace_point_count"),
                "scpi_trace_mode": result.get("scpi_trace_mode", ""),
                "scpi_detector": result.get("scpi_detector", ""),
                "scpi_average_enabled": result.get("scpi_average_enabled"),
                "scpi_avg_count": result.get("scpi_avg_count"),
            },
        )


class PsdProcedure(SpectrumProcedure):
    name = "PSD"

    def _use_real_backend(self, inst: InstrumentSession) -> bool:
        detection = detect_keysight_xseries_analyzer(inst)
        return bool(detection.get("usable"))

    def _supports_generic_trace_flow(self, inst: InstrumentSession) -> bool:
        return hasattr(inst, "configure") and hasattr(inst, "acquire_trace")

    def precheck(self, ctx: CaseContext, inst: InstrumentSession) -> Optional[StepResult]:
        detection = detect_keysight_xseries_analyzer(inst)
        backend = "real" if detection.get("usable") else "mock"
        if not detection.get("usable") and not self._supports_generic_trace_flow(inst):
            return StepResult(
                step_name="PREFLIGHT",
                status="ERROR",
                message=(
                    f"Instrument '{type(inst).__name__}' does not support PSD generic trace flow "
                    "(requires configure() and acquire_trace()) and is not a supported Keysight X-series analyzer."
                ),
                data={
                    "procedure": self.name,
                    "test_type": ctx.case.test_type,
                    "measurement_source": backend,
                    "backend_reason": detection.get("reason", "unknown"),
                    "backend_idn": detection.get("idn", ""),
                    "missing_capabilities": [
                        name for name in ("configure", "acquire_trace") if not hasattr(inst, name)
                    ],
                },
            )
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
        if self._use_real_backend(inst):
            return []
        return [ConfigureInstrumentStep()]

    def acquire_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        if self._use_real_backend(inst):
            return [PsdMeasureStep()]
        return [AcquireTraceStep()]

    def compute_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        if self._use_real_backend(inst):
            return []
        return [ComputeMetricsStep()]

    def evaluate_steps(self, ctx: CaseContext, inst: InstrumentSession) -> List[Step]:
        if self._use_real_backend(inst):
            return []
        return [JudgeStep()]


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

        resolved_profile = build_consumable_measurement_profile(
            test_type=getattr(ctx.case, "test_type", ""),
            resolved_profile=dict(ctx.values.get("resolved_profile") or {}),
            instrument_snapshot=dict(getattr(ctx.case, "instrument", {}) or {}),
        )
        ctx.values["resolved_profile"] = dict(resolved_profile)

        try:
            result = (
                measure_obw_keysight(inst, ctx.case, profile_settings=resolved_profile)
                if use_real
                else mock_obw_measurement(ctx.case)
            )
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
                "measurement_profile_name": resolved_profile.get("profile_name", ""),
                "measurement_profile_source": resolved_profile.get("profile_source", ""),
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
