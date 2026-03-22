from __future__ import annotations
from typing import Any, Dict

from domain.steps import CaseContext, StepResult


class ConfigureInstrumentStep:
    name = "CONFIGURE"

    def run(self, ctx: CaseContext, inst) -> StepResult:
        try:
            inst.configure(ctx.case.instrument)  # case.instrument snapshot 사용
            ctx.values["instrument_used"] = dict(ctx.case.instrument)
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
    test_type별로 계산이 달라야 하므로, 일단 MVP는 간단히 test_type switch로 시작
    나중에는 PSDComputeStep/OBWComputeStep로 쪼개면 됨.
    """
    name = "COMPUTE"

    def run(self, ctx: CaseContext, inst) -> StepResult:
        try:
            test_type = ctx.case.test_type
            trace = ctx.values.get("trace", {}).get("trace", [])
            if not trace:
                return StepResult(step_name=self.name, status="ERROR", message="No trace")

            # MVP 계산(가짜)
            measured = max(trace)  # peak
            ctx.values["measured_value"] = measured

            # 가짜 limit (나중엔 ruleset/limit 테이블로)
            limit = -30.0 if test_type == "PSD" else -20.0
            ctx.values["limit_value"] = limit
            ctx.values["margin_db"] = limit - measured  # measured가 높으면 margin 음수

            return StepResult(step_name=self.name, status="OK", data={
                "measured_value": measured,
                "limit_value": limit,
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