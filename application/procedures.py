from __future__ import annotations
from typing import Dict, List

from domain.steps import Step
from application.steps_common import ConfigureInstrumentStep, AcquireTraceStep, ComputeMetricsStep, JudgeStep


class ProcedureRegistry:
    """
    test_type -> steps
    """
    def __init__(self):
        self._map: Dict[str, List[Step]] = {}

        # MVP: test_type별로 같은 스텝 구성, 나중에 test_type별 compute step 분리
        common = [ConfigureInstrumentStep(), AcquireTraceStep(), ComputeMetricsStep(), JudgeStep()]
        self._map["PSD"] = common
        self._map["OBW"] = common
        self._map["SP"]  = common
        self._map["RX"] = common

    def get_steps(self, test_type: str) -> List[Step]:
        if test_type not in self._map:
            raise KeyError(f"No procedure for test_type={test_type}")
        return self._map[test_type]