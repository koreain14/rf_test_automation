from __future__ import annotations

from application.executors.base_executor import BaseExecutor
from application.measurements.keysight_obw_helper import KeysightObwConfig, mock_obw_measurement
from domain.execution import MeasurementStep, RunContext, StepExecutionResult


class ObwExecutor(BaseExecutor):
    def execute(self, step: MeasurementStep, context: RunContext) -> StepExecutionResult:
        profile = dict(step.metadata.get("resolved_profile") or step.parameters or {})
        span_hz = profile.get("span_hz") or max(int((step.bandwidth_mhz or 20) * 2_000_000), 10_000_000)
        cfg = KeysightObwConfig(
            center_freq_hz=float(step.frequency_mhz or 0.0) * 1_000_000.0,
            span_hz=float(span_hz),
            rbw_hz=float(profile.get("rbw_hz") or 10_000),
            vbw_hz=float(profile.get("vbw_hz") or 30_000),
            detector=str(profile.get("detector") or "PEAK"),
            trace_mode=str(profile.get("trace_mode") or "MAXHOLD"),
        )
        measured_mhz, raw = mock_obw_measurement(cfg)
        limit_value = float(step.bandwidth_mhz or 20)
        margin = limit_value - measured_mhz
        status = "DONE" if margin >= 0 else "FAIL"
        return StepExecutionResult(
            step_id=step.step_id,
            status=status,
            measured_value=measured_mhz,
            unit="MHz",
            limit_value=limit_value,
            margin=margin,
            message="OBW preview executor (mock)",
            raw_data={
                "channel": step.channel,
                "frequency_mhz": step.frequency_mhz,
                "bandwidth_mhz": step.bandwidth_mhz,
                "dry_run": context.dry_run,
                **raw,
            },
        )
