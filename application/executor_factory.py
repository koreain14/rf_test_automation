from __future__ import annotations

from application.test_type_symbols import normalize_test_type_symbol
from application.executors.obw_executor import ObwExecutor
from application.executors.psd_executor import PsdExecutor


class ExecutorFactory:
    @staticmethod
    def _normalize_test_type(test_type: str) -> str:
        return normalize_test_type_symbol(test_type)

    @staticmethod
    def get_executor(step):
        test_type = ExecutorFactory._normalize_test_type(getattr(step, "test_type", ""))
        if test_type == "PSD":
            return PsdExecutor()
        if test_type == "OBW":
            return ObwExecutor()
        raise ValueError(f"Unsupported test_type: {test_type}")
