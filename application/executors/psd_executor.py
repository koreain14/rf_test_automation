from __future__ import annotations

from application.executors.base_executor import BaseExecutor
from domain.execution import MeasurementStep, RunContext, StepExecutionResult


class PsdExecutor(BaseExecutor):
    def execute(self, step: MeasurementStep, context: RunContext) -> StepExecutionResult:
        return StepExecutionResult(
            step_id=step.step_id,
            status="DONE",
            measured_value=0.0,
            unit="dBm/MHz",
            message="PSD executor placeholder",
            raw_data={
                "channel": step.channel,
                "frequency_mhz": step.frequency_mhz,
                "bandwidth_mhz": step.bandwidth_mhz,
                "dry_run": context.dry_run,
            },
        )
