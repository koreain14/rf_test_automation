from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, List

from domain.models import TestCase


@dataclass
class StepResult:
    step_name: str
    status: str                 # OK/FAIL/ERROR (step 자체의 성공/실패)
    data: Dict[str, Any] = field(default_factory=dict)
    artifact_uri: Optional[str] = None
    message: str = ""


@dataclass
class CaseContext:
    """
    케이스 하나를 처리하는 동안의 '공용 메모리'
    - step들이 여기다가 trace, 계산값, limit, 판정 등을 넣고 공유
    """
    case: TestCase
    values: Dict[str, Any] = field(default_factory=dict)


class InstrumentSession(Protocol):
    """
    나중에 진짜 장비 연결(PSA/FSW/ESW/9030B 등)을 여기 인터페이스로 숨긴다.
    프로토타입 단계에서는 Dummy 구현으로 시작.
    """
    def configure(self, settings: Dict[str, Any]) -> None: ...
    def acquire_trace(self) -> Dict[str, Any]: ...


class Step(Protocol):
    name: str
    def run(self, ctx: CaseContext, inst: InstrumentSession) -> StepResult: ...
    
class DutSession(Protocol):
    def apply_rf_config(self, cfg: Dict[str, Any]) -> None: ...