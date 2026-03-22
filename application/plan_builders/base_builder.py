from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from application.preset_model import PresetModel


class BasePlanBuilder(ABC):
    @abstractmethod
    def build_steps(self, model: PresetModel) -> list[dict[str, Any]]:
        raise NotImplementedError
