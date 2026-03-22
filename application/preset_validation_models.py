from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PresetValidationIssue:
    level: str
    message: str


@dataclass
class PresetValidationResult:
    issues: list[PresetValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level.upper() == "ERROR" for i in self.issues)

    def add_error(self, message: str) -> None:
        self.issues.append(PresetValidationIssue(level="ERROR", message=message))

    def add_warning(self, message: str) -> None:
        self.issues.append(PresetValidationIssue(level="WARNING", message=message))

    def summary(self) -> str:
        if not self.issues:
            return "OK"
        return "\n".join(f"[{i.level}] {i.message}" for i in self.issues)
