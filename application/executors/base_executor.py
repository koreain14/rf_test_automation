from __future__ import annotations

from abc import ABC, abstractmethod

from domain.execution import MeasurementStep, RunContext, StepExecutionResult


class BaseExecutor(ABC):
    @abstractmethod
    def execute(self, step: MeasurementStep, context: RunContext) -> StepExecutionResult:
        raise NotImplementedError
