from __future__ import annotations

from PySide6.QtWidgets import QWidget

from application.preset_model import PresetModel


class BaseExpansionEditor(QWidget):
    def load_from_model(self, preset: PresetModel) -> None:
        raise NotImplementedError

    def apply_to_model(self, preset: PresetModel) -> None:
        raise NotImplementedError

    def validate_messages(self) -> list[str]:
        return []

    def expansion_type(self) -> str:
        raise NotImplementedError
