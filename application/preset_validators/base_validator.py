from __future__ import annotations

from application.preset_model import PresetModel
from application.preset_validation_models import PresetValidationResult


class BasePresetExtensionValidator:
    def validate(self, model: PresetModel, result: PresetValidationResult) -> None:
        raise NotImplementedError
