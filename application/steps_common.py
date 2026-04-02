from __future__ import annotations
from typing import Any, Dict

from domain.steps import CaseContext, StepResult


class ConfigureInstrumentStep:
    name = "CONFIGURE"

    def run(self, ctx: CaseContext, inst) -> StepResult:
        try:
            settings = dict(ctx.values.get("resolved_profile") or getattr(ctx.case, "instrument", {}) or {})
            inst.configure(settings)
            ctx.values["instrument_used"] = dict(settings)
            return StepResult(step_name=self.name, status="OK")
        except Exception as e:
            return StepResult(step_name=self.name, status="ERROR", message=str(e))


class AcquireTraceStep:
    name = "ACQUIRE"

    def run(self, ctx: CaseContext, inst) -> StepResult:
        try:
            trace = inst.acquire_trace()
            ctx.values["trace"] = trace
            return StepResult(step_name=self.name, status="OK", data={"points": len(trace.get("trace", []))})
        except Exception as e:
            return StepResult(step_name=self.name, status="ERROR", message=str(e))


class ComputeMetricsStep:
    """
    test_type별 계산 로직은 향후 분리 가능하지만, 현재는 최소 공통 구현을 유지한다.
    """
    name = "COMPUTE"

    def run(self, ctx: CaseContext, inst) -> StepResult:
        try:
            test_type = ctx.case.test_type
            trace = ctx.values.get("trace", {}).get("trace", [])
            if not trace:
                return StepResult(step_name=self.name, status="ERROR", message="No trace")

            measured = max(trace)
            ctx.values["measured_value"] = measured

            limit = -30.0 if test_type == "PSD" else -20.0
            ctx.values["limit_value"] = limit
            ctx.values["difference_value"] = measured - limit
            ctx.values["difference_unit"] = str(ctx.values.get("measurement_unit", "") or "")
            ctx.values["comparator"] = "upper_limit"
            ctx.values["margin_db"] = limit - measured

            return StepResult(step_name=self.name, status="OK", data={
                "measured_value": measured,
                "limit_value": limit,
                "difference_value": ctx.values["difference_value"],
                "difference_unit": ctx.values["difference_unit"],
                "comparator": ctx.values["comparator"],
                "margin_db": ctx.values["margin_db"],
            })
        except Exception as e:
            return StepResult(step_name=self.name, status="ERROR", message=str(e))


class JudgeStep:
    name = "JUDGE"

    def run(self, ctx: CaseContext, inst) -> StepResult:
        try:
            margin = ctx.values.get("margin_db")
            if margin is None:
                return StepResult(step_name=self.name, status="ERROR", message="No margin_db")

            verdict = "PASS" if margin >= 0 else "FAIL"
            ctx.values["verdict"] = verdict
            return StepResult(step_name=self.name, status="OK", data={"verdict": verdict})
        except Exception as e:
            return StepResult(step_name=self.name, status="ERROR", message=str(e))
