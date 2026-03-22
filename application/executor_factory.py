from __future__ import annotations

from application.executors.obw_executor import ObwExecutor
from application.executors.psd_executor import PsdExecutor


class ExecutorFactory:
    @staticmethod
    def get_executor(step):
        test_type = str(step.test_type).upper()
        if test_type == "PSD":
            return PsdExecutor()
        if test_type == "OBW":
            return ObwExecutor()
        raise ValueError(f"Unsupported test_type: {test_type}")
