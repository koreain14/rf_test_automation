from __future__ import annotations

from application.executors.base_executor import BaseExecutor
from application.psd_unit_policy import psd_unit_label
from domain.execution import MeasurementStep, RunContext, StepExecutionResult


class PsdExecutor(BaseExecutor):
    def execute(self, step: MeasurementStep, context: RunContext) -> StepExecutionResult:
        unit_policy = str((step.metadata or {}).get("psd_result_unit", "") or "")
        method = str((step.metadata or {}).get("psd_method", "") or "")
        return StepExecutionResult(
            step_id=step.step_id,
            status="DONE",
            measured_value=0.0,
            unit=psd_unit_label(unit_policy),
            message="PSD executor placeholder",
            raw_data={
                "channel": step.channel,
                "frequency_mhz": step.frequency_mhz,
                "bandwidth_mhz": step.bandwidth_mhz,
                "dry_run": context.dry_run,
                "psd_method": method,
                "psd_result_unit": unit_policy,
            },
        )
