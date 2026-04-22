from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Dict, List, Optional

from application.analyzer_screenshot import capture_analyzer_screenshot_best_effort
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
from application.measurements.keysight_txp_helper import measure_txp_keysight, mock_txp_measurement
from application.psd_unit_policy import (
    PSD_CANONICAL_UNIT,
    PSD_METHOD_AVERAGE,
    PSD_METHOD_MARKER_PEAK,
    build_psd_display_payload,
    convert_psd_value,
    normalize_psd_method,
    normalize_psd_result_unit,
    psd_scpi_power_unit,
)

log = logging.getLogger(__name__)


def _apply_screenshot_to_context(ctx: CaseContext, screenshot: dict) -> None:
    if not screenshot:
        return
    for key in (
        "screenshot_capture_status",
        "screenshot_capture_error",
        "screenshot_path",
        "screenshot_abs_path",
        "screenshot_root_dir",
        "screenshot_requested_root_dir",
        "screenshot_storage_mode",
        "screenshot_fallback_used",
        "screenshot_strategy",
        "screenshot_backend_idn",
        "screenshot_file_name",
        "screenshot_size_bytes",
    ):
        if key in screenshot:
            ctx.values[key] = screenshot.get(key)
    ctx.values["screenshot_capture_done"] = True


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
        if ctx.values.get("screenshot_capture_done"):
            return None
        screenshot = capture_analyzer_screenshot_best_effort(
            inst,
            run_id=str(ctx.values.get("run_id", "") or ""),
            result_id=str(ctx.values.get("result_id", "") or ""),
            case=ctx.case,
            requested_root_dir=str(ctx.values.get("screenshot_root_dir", "") or ""),
            settle_ms=ctx.values.get("screenshot_settle_ms", 300),
        )
        _apply_screenshot_to_context(ctx, screenshot)
        status = "OK" if screenshot.get("screenshot_capture_status") == "captured" else "INFO"
        return StepResult(
            step_name="SCREENSHOT",
            status=status,
            artifact_uri=screenshot.get("screenshot_abs_path") or None,
            data=screenshot,
            message=screenshot.get("screenshot_capture_error", ""),
        )

    @staticmethod
    def _apply_screenshot_to_context(ctx: CaseContext, screenshot: dict) -> None:
        _apply_screenshot_to_context(ctx, screenshot)
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
        log.info(
            "procedure execute ctx | procedure=%s case=%s test_type=%s standard=%s data_rate=%s voltage_condition=%s nominal_voltage_v=%s target_voltage_v=%s axis_values=%s",
            self.name,
            getattr(ctx.case, "key", ""),
            getattr(ctx.case, "test_type", ""),
            ctx.values.get("standard", getattr(ctx.case, "standard", "")),
            ctx.values.get("data_rate", ""),
            ctx.values.get("voltage_condition", ""),
            ctx.values.get("nominal_voltage_v"),
            ctx.values.get("target_voltage_v"),
            ctx.values.get("axis_values", {}),
        )
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

    @staticmethod
    def _method_from_case(case) -> str:
        tags = dict(getattr(case, "tags", {}) or {})
        return normalize_psd_method(tags.get("psd_method")) or PSD_METHOD_MARKER_PEAK

    @staticmethod
    def _comparator_from_case(case) -> str:
        tags = dict(getattr(case, "tags", {}) or {})
        return str(tags.get("psd_comparator", "upper_limit") or "upper_limit")

    @staticmethod
    def _limit_from_case(case, display_unit: str) -> tuple[float, float, str]:
        tags = dict(getattr(case, "tags", {}) or {})
        raw_limit = tags.get("psd_limit_value")
        limit_unit = normalize_psd_result_unit(tags.get("psd_limit_unit")) or display_unit
        try:
            ruleset_limit_value = float(raw_limit)
        except Exception:
            ruleset_limit_value = convert_psd_value(-30.0, from_unit=PSD_CANONICAL_UNIT, to_unit=limit_unit)
        canonical_limit = convert_psd_value(
            ruleset_limit_value,
            from_unit=limit_unit,
            to_unit=PSD_CANONICAL_UNIT,
        )
        stored_limit_value = convert_psd_value(
            canonical_limit,
            from_unit=PSD_CANONICAL_UNIT,
            to_unit=display_unit,
        )
        return stored_limit_value, canonical_limit, limit_unit

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
                result = measure_psd_keysight(
                    inst,
                    ctx.case,
                    profile_settings=resolved_profile,
                    screenshot_context={
                        "run_id": ctx.values.get("run_id", ""),
                        "result_id": ctx.values.get("result_id", ""),
                        "screenshot_root_dir": ctx.values.get("screenshot_root_dir", ""),
                        "screenshot_settle_ms": ctx.values.get("screenshot_settle_ms", 300),
                    },
                )
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
                display_unit = self._display_unit_from_case(ctx.case)
                psd_method = self._method_from_case(ctx.case)
                comparator = self._comparator_from_case(ctx.case)
                if psd_method == PSD_METHOD_AVERAGE:
                    measured = sum(float(x) for x in trace) / float(len(trace))
                else:
                    measured = max(float(x) for x in trace)
                limit_value, canonical_limit, limit_unit = self._limit_from_case(ctx.case, display_unit)
                canonical_measured = convert_psd_value(
                    measured,
                    from_unit=display_unit,
                    to_unit=PSD_CANONICAL_UNIT,
                )
                difference_value = round(measured - limit_value, 6)
                margin = canonical_limit - canonical_measured
                display_payload = build_psd_display_payload(
                    canonical_value_dbm_per_mhz=canonical_measured,
                    display_unit=display_unit,
                )
                display_limit_payload = build_psd_display_payload(
                    canonical_value_dbm_per_mhz=canonical_limit,
                    display_unit=display_unit,
                )
                result = {
                    "measured_value": measured,
                    "limit_value": limit_value,
                    "margin_db": margin,
                    "measurement_unit": self._display_unit_label(display_unit),
                    "canonical_measurement_unit": self._display_unit_label(PSD_CANONICAL_UNIT),
                    "canonical_measured_value": canonical_measured,
                    "canonical_limit_value": canonical_limit,
                    "psd_result_unit": display_payload["display_unit"],
                    "psd_canonical_unit": display_payload["canonical_unit"],
                    "psd_method": psd_method,
                    "psd_limit_value": float((getattr(ctx.case, "tags", {}) or {}).get("psd_limit_value") or limit_value),
                    "psd_limit_unit": limit_unit,
                    "psd_limit_label": self._display_unit_label(limit_unit),
                    "psd_unit_policy_source": str((getattr(ctx.case, "tags", {}) or {}).get("psd_unit_policy_source", "")),
                    "difference_value": difference_value,
                    "difference_unit": self._display_unit_label(display_unit),
                    "comparator": comparator,
                    "display_measured_value": display_payload["display_value"],
                    "display_limit_value": display_limit_payload["display_value"],
                    "display_measurement_unit": self._display_unit_label(display_payload["display_unit"]),
                    "scpi_power_unit": psd_scpi_power_unit(display_unit),
                    "scpi_measurement_method": psd_method,
                    "ruleset_id": str((getattr(ctx.case, "tags", {}) or {}).get("ruleset_id", "")),
                    "device_class": str((getattr(ctx.case, "tags", {}) or {}).get("device_class", "")),
                    "measurement_source": "mock",
                    "backend_reason": reason,
                    "backend_idn": idn,
                    "measurement_profile_name": resolved_profile.get("profile_name", ""),
                    "measurement_profile_source": resolved_profile.get("profile_source", ""),
                    "measurement_profile_precedence": resolved_profile.get("measurement_profile_precedence", "measurement_profile_wins_over_instrument_snapshot"),
                    "measurement_profile_span_source": "profile_or_generic_mock",
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
                    "measurement_profile_precedence": resolved_profile.get("measurement_profile_precedence", "measurement_profile_wins_over_instrument_snapshot"),
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
        if result.get("measurement_profile_span_source"):
            ctx.values["measurement_profile_span_source"] = result.get("measurement_profile_span_source")
        if result.get("measurement_profile_precedence"):
            ctx.values["measurement_profile_precedence"] = result.get("measurement_profile_precedence")
        if result.get("scpi_trace_mode"):
            ctx.values["scpi_trace_mode"] = result.get("scpi_trace_mode")
        if result.get("scpi_detector"):
            ctx.values["scpi_detector"] = result.get("scpi_detector")
        if result.get("scpi_average_enabled") is not None:
            ctx.values["scpi_average_enabled"] = result.get("scpi_average_enabled")
        if result.get("scpi_avg_count") is not None:
            ctx.values["scpi_avg_count"] = result.get("scpi_avg_count")
        if result.get("scpi_power_unit"):
            ctx.values["scpi_power_unit"] = result.get("scpi_power_unit")
        if result.get("psd_method"):
            ctx.values["psd_method"] = result.get("psd_method")
        if result.get("psd_limit_value") is not None:
            ctx.values["psd_limit_value"] = result.get("psd_limit_value")
        if result.get("psd_limit_unit"):
            ctx.values["psd_limit_unit"] = result.get("psd_limit_unit")
        if result.get("psd_limit_label"):
            ctx.values["psd_limit_label"] = result.get("psd_limit_label")
        if result.get("trace_point_count") is not None:
            ctx.values["trace_point_count"] = result.get("trace_point_count")
        if result.get("display_measured_value") is not None:
            ctx.values["display_measured_value"] = result.get("display_measured_value")
        if result.get("display_limit_value") is not None:
            ctx.values["display_limit_value"] = result.get("display_limit_value")
        if result.get("display_measurement_unit"):
            ctx.values["display_measurement_unit"] = result.get("display_measurement_unit")
        if result.get("difference_value") is not None:
            ctx.values["difference_value"] = result.get("difference_value")
        if result.get("difference_unit"):
            ctx.values["difference_unit"] = result.get("difference_unit")
        if result.get("comparator"):
            ctx.values["comparator"] = result.get("comparator")
        if result.get("psd_result_unit"):
            ctx.values["psd_result_unit"] = result.get("psd_result_unit")
        if result.get("psd_canonical_unit"):
            ctx.values["psd_canonical_unit"] = result.get("psd_canonical_unit")
        if result.get("psd_unit_policy_source"):
            ctx.values["psd_unit_policy_source"] = result.get("psd_unit_policy_source")
        if result.get("canonical_measured_value") is not None:
            ctx.values["canonical_measured_value"] = result.get("canonical_measured_value")
        if result.get("canonical_limit_value") is not None:
            ctx.values["canonical_limit_value"] = result.get("canonical_limit_value")
        _apply_screenshot_to_context(ctx, result)
        ctx.values["verdict"] = result.get("verdict", "ERROR")

        return StepResult(
            step_name=self.name,
            status="OK",
            artifact_uri=result.get("screenshot_abs_path") or None,
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
                "measurement_profile_precedence": result.get("measurement_profile_precedence", resolved_profile.get("measurement_profile_precedence", "measurement_profile_wins_over_instrument_snapshot")),
                "measurement_profile_span_source": result.get("measurement_profile_span_source", ""),
                "canonical_measurement_unit": result.get("canonical_measurement_unit", "dBm/MHz"),
                "canonical_measured_value": result.get("canonical_measured_value"),
                "canonical_limit_value": result.get("canonical_limit_value"),
                "psd_result_unit": result.get("psd_result_unit", ""),
                "psd_canonical_unit": result.get("psd_canonical_unit", PSD_CANONICAL_UNIT),
                "psd_method": result.get("psd_method", ""),
                "psd_limit_value": result.get("psd_limit_value"),
                "psd_limit_unit": result.get("psd_limit_unit", ""),
                "psd_limit_label": result.get("psd_limit_label", ""),
                "psd_unit_policy_source": result.get("psd_unit_policy_source", ""),
                "display_measured_value": result.get("display_measured_value"),
                "display_limit_value": result.get("display_limit_value"),
                "display_measurement_unit": result.get("display_measurement_unit", "dBm/MHz"),
                "difference_value": result.get("difference_value"),
                "difference_unit": result.get("difference_unit", result.get("measurement_unit", "")),
                "comparator": result.get("comparator", "upper_limit"),
                "scpi_power_unit": result.get("scpi_power_unit", ""),
                "scpi_measurement_method": result.get("scpi_measurement_method", ""),
                "ruleset_id": result.get("ruleset_id", ""),
                "device_class": result.get("device_class", ""),
                "trace_point_count": result.get("trace_point_count"),
                "scpi_trace_mode": result.get("scpi_trace_mode", ""),
                "scpi_detector": result.get("scpi_detector", ""),
                "scpi_average_enabled": result.get("scpi_average_enabled"),
                "scpi_avg_count": result.get("scpi_avg_count"),
                "screenshot_capture_status": result.get("screenshot_capture_status", ""),
                "screenshot_capture_error": result.get("screenshot_capture_error", ""),
                "screenshot_path": result.get("screenshot_path", ""),
                "screenshot_abs_path": result.get("screenshot_abs_path", ""),
                "screenshot_root_dir": result.get("screenshot_root_dir", ""),
                "screenshot_storage_mode": result.get("screenshot_storage_mode", ""),
                "screenshot_fallback_used": result.get("screenshot_fallback_used", False),
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
                measure_obw_keysight(
                    inst,
                    ctx.case,
                    profile_settings=resolved_profile,
                    screenshot_context={
                        "run_id": ctx.values.get("run_id", ""),
                        "result_id": ctx.values.get("result_id", ""),
                        "screenshot_root_dir": ctx.values.get("screenshot_root_dir", ""),
                        "screenshot_settle_ms": ctx.values.get("screenshot_settle_ms", 300),
                    },
                )
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
                    "measurement_profile_precedence": resolved_profile.get("measurement_profile_precedence", "measurement_profile_wins_over_instrument_snapshot"),
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
        if result.get("difference_value") is not None:
            ctx.values["difference_value"] = result.get("difference_value")
        if result.get("difference_unit"):
            ctx.values["difference_unit"] = result.get("difference_unit")
        if result.get("comparator"):
            ctx.values["comparator"] = result.get("comparator")
        _apply_screenshot_to_context(ctx, result)

        return StepResult(
            step_name=self.name,
            status="OK",
            artifact_uri=result.get("screenshot_abs_path") or None,
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
                "measurement_profile_precedence": resolved_profile.get("measurement_profile_precedence", "measurement_profile_wins_over_instrument_snapshot"),
                "difference_value": result.get("difference_value"),
                "difference_unit": result.get("difference_unit", result.get("measurement_unit", "")),
                "comparator": result.get("comparator", "upper_limit"),
                "screenshot_capture_status": result.get("screenshot_capture_status", ""),
                "screenshot_capture_error": result.get("screenshot_capture_error", ""),
                "screenshot_path": result.get("screenshot_path", ""),
                "screenshot_abs_path": result.get("screenshot_abs_path", ""),
                "screenshot_root_dir": result.get("screenshot_root_dir", ""),
                "screenshot_storage_mode": result.get("screenshot_storage_mode", ""),
                "screenshot_fallback_used": result.get("screenshot_fallback_used", False),
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


class TxpMeasureStep:
    name = "TXP_MEASURE"

    def run(self, ctx: CaseContext, inst) -> StepResult:
        detection = detect_keysight_xseries_analyzer(inst)
        use_real = bool(detection.get("usable"))
        backend = "real" if use_real else "mock"
        reason = str(detection.get("reason") or "unknown")
        idn = str(detection.get("idn") or "")
        source_class = str(detection.get("source_class") or type(inst).__name__)
        log.info(
            "txp backend selected | case=%s backend=%s reason=%s source_class=%s idn=%s",
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
            result = (
                measure_txp_keysight(
                    inst,
                    ctx.case,
                    profile_settings=resolved_profile,
                    screenshot_context={
                        "run_id": ctx.values.get("run_id", ""),
                        "result_id": ctx.values.get("result_id", ""),
                        "screenshot_root_dir": ctx.values.get("screenshot_root_dir", ""),
                        "screenshot_settle_ms": ctx.values.get("screenshot_settle_ms", 300),
                    },
                )
                if use_real
                else mock_txp_measurement(ctx.case)
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
                    "measurement_profile_precedence": resolved_profile.get("measurement_profile_precedence", "measurement_profile_wins_over_instrument_snapshot"),
                },
            )

        ctx.values["measured_value"] = result["measured_value"]
        if result.get("raw_measured_value") is not None:
            ctx.values["raw_measured_value"] = result.get("raw_measured_value")
        ctx.values["limit_value"] = result["limit_value"]
        ctx.values["margin_db"] = result["margin_db"]
        ctx.values["measurement_unit"] = result.get("measurement_unit", "dBm")
        ctx.values["measurement_source"] = result.get("measurement_source", backend)
        ctx.values["backend_reason"] = result.get("backend_reason", reason)
        if result.get("backend_idn"):
            ctx.values["backend_idn"] = result.get("backend_idn")
        if result.get("error_message"):
            ctx.values["error_message"] = result.get("error_message")
        if result.get("difference_value") is not None:
            ctx.values["difference_value"] = result.get("difference_value")
        if result.get("difference_unit"):
            ctx.values["difference_unit"] = result.get("difference_unit")
        if result.get("comparator"):
            ctx.values["comparator"] = result.get("comparator")
        if result.get("measurement_profile_span_source"):
            ctx.values["measurement_profile_span_source"] = result.get("measurement_profile_span_source")
        if result.get("measurement_profile_precedence"):
            ctx.values["measurement_profile_precedence"] = result.get("measurement_profile_precedence")
        if result.get("scpi_trace_mode"):
            ctx.values["scpi_trace_mode"] = result.get("scpi_trace_mode")
        if result.get("scpi_detector"):
            ctx.values["scpi_detector"] = result.get("scpi_detector")
        if result.get("scpi_average_enabled") is not None:
            ctx.values["scpi_average_enabled"] = result.get("scpi_average_enabled")
        if result.get("scpi_avg_count") is not None:
            ctx.values["scpi_avg_count"] = result.get("scpi_avg_count")
        if result.get("scpi_power_unit"):
            ctx.values["scpi_power_unit"] = result.get("scpi_power_unit")
        _apply_screenshot_to_context(ctx, result)
        ctx.values["verdict"] = result.get("verdict", "ERROR")

        return StepResult(
            step_name=self.name,
            status="OK",
            artifact_uri=result.get("screenshot_abs_path") or None,
            data={
                "measured_value": result["measured_value"],
                "raw_measured_value": result.get("raw_measured_value"),
                "limit_value": result["limit_value"],
                "margin_db": result["margin_db"],
                "measurement_unit": result.get("measurement_unit", "dBm"),
                "measurement_source": result.get("measurement_source", backend),
                "backend_reason": result.get("backend_reason", reason),
                "backend_idn": result.get("backend_idn", idn),
                "measurement_profile_name": resolved_profile.get("profile_name", ""),
                "measurement_profile_source": resolved_profile.get("profile_source", ""),
                "measurement_profile_precedence": result.get("measurement_profile_precedence", resolved_profile.get("measurement_profile_precedence", "measurement_profile_wins_over_instrument_snapshot")),
                "measurement_profile_span_source": result.get("measurement_profile_span_source", ""),
                "difference_value": result.get("difference_value"),
                "difference_unit": result.get("difference_unit", result.get("measurement_unit", "")),
                "comparator": result.get("comparator", "upper_limit"),
                "scpi_power_unit": result.get("scpi_power_unit", ""),
                "scpi_measurement_method": result.get("scpi_measurement_method", "CHP"),
                "ruleset_id": result.get("ruleset_id", ""),
                "device_class": result.get("device_class", ""),
                "scpi_trace_mode": result.get("scpi_trace_mode", ""),
                "scpi_detector": result.get("scpi_detector", ""),
                "scpi_average_enabled": result.get("scpi_average_enabled"),
                "scpi_avg_count": result.get("scpi_avg_count"),
                "screenshot_capture_status": result.get("screenshot_capture_status", ""),
                "screenshot_capture_error": result.get("screenshot_capture_error", ""),
                "screenshot_path": result.get("screenshot_path", ""),
                "screenshot_abs_path": result.get("screenshot_abs_path", ""),
                "screenshot_root_dir": result.get("screenshot_root_dir", ""),
                "screenshot_storage_mode": result.get("screenshot_storage_mode", ""),
                "screenshot_fallback_used": result.get("screenshot_fallback_used", False),
            },
        )


class TxpProcedure(SpectrumProcedure):
    name = "TXP"

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
        return [TxpMeasureStep()]

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
            "TXP": TxpProcedure(),
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
