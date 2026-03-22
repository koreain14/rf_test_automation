from __future__ import annotations

from typing import Iterable

from application.preset_model import PresetModel
from application.preset_validation_models import PresetValidationResult
from application.preset_validators.wlan_validator import WlanPresetValidator

ALLOWED_CHANNEL_POLICIES = {
    "CUSTOM_LIST",
    "LOW_MID_HIGH_BY_GROUP",
}

ALLOWED_EXECUTION_TYPES = {
    "CHANNEL_CENTRIC",
    "TEST_CENTRIC",
}


class PresetValidator:
    def __init__(self) -> None:
        self._wlan_validator = WlanPresetValidator()

    def validate(self, model: PresetModel) -> PresetValidationResult:
        result = PresetValidationResult()
        sel = model.selection

        if not model.name.strip():
            result.add_error("Preset name is required.")
        if not model.ruleset_id.strip():
            result.add_error("RuleSet ID is required.")
        if not model.ruleset_version.strip():
            result.add_warning("RuleSet version is empty.")
        if not sel.band.strip():
            result.add_error("Band is required.")
        has_wlan_expansion = _has_wlan_expansion(model)

        if _looks_like_wlan(model) and not has_wlan_expansion:
            result.add_error("WLAN preset requires WLAN Expansion rows.")
        elif not sel.standard.strip() and not has_wlan_expansion:
            result.add_error("Standard is required.")
        if not sel.test_types:
            result.add_error("At least one test type is required.")
        if not sel.bandwidth_mhz and not has_wlan_expansion:
            result.add_error("At least one bandwidth is required.")
        if not sel.channels.channels and not has_wlan_expansion:
            result.add_error("At least one channel is required.")

        if not has_wlan_expansion and sel.channels.policy not in ALLOWED_CHANNEL_POLICIES:
            result.add_error(
                f"Unsupported channel policy: {sel.channels.policy}. Allowed: {sorted(ALLOWED_CHANNEL_POLICIES)}"
            )

        if sel.execution_policy.type not in ALLOWED_EXECUTION_TYPES:
            result.add_error(
                f"Unsupported execution policy type: {sel.execution_policy.type}. Allowed: {sorted(ALLOWED_EXECUTION_TYPES)}"
            )

        if sel.bandwidth_mhz:
            self._validate_positive_ints(result, "Bandwidth", sel.bandwidth_mhz)
        if sel.channels.channels:
            self._validate_positive_ints(result, "Channel", sel.channels.channels)

        duplicated_tests = _find_duplicates(sel.test_types)
        if duplicated_tests:
            result.add_warning(f"Duplicate test types found: {duplicated_tests}")

        missing_exec = [tt for tt in sel.test_types if tt not in sel.execution_policy.test_order]
        if missing_exec:
            result.add_warning(
                f"Execution order does not include selected test types: {missing_exec}. Default runner order may differ."
            )

        if _looks_like_wlan(model):
            self._wlan_validator.validate(model, result)

        return result

    @staticmethod
    def _validate_positive_ints(result: PresetValidationResult, label: str, values: Iterable[int]) -> None:
        for v in values:
            try:
                iv = int(v)
            except Exception:
                result.add_error(f"{label} value '{v}' is not a valid integer.")
                continue
            if iv <= 0:
                result.add_error(f"{label} value must be positive: {iv}")


def _find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dup: list[str] = []
    for v in values:
        if v in seen and v not in dup:
            dup.append(v)
        seen.add(v)
    return dup


def _looks_like_wlan(model: PresetModel) -> bool:
    rid = str(model.ruleset_id or "").upper()
    std = str(model.selection.standard or "").upper()
    return ("WLAN" in rid) or std.startswith("802.11")


def _has_wlan_expansion(model: PresetModel) -> bool:
    sel = model.selection
    if sel.wlan_expansion is not None:
        return bool(sel.wlan_expansion.mode_plan or sel.wlan_expansion.channel_plan)
    meta = dict(sel.metadata or {})
    wlan = dict(meta.get("wlan_expansion") or {})
    return bool(wlan.get("mode_plan") or wlan.get("channel_plan"))
