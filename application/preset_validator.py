from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from application.preset_migration import analyze_preset_model
from application.preset_model import PresetModel
from application.preset_validation_models import PresetValidationResult
from application.preset_validator_registry import PresetValidatorRegistry
from application.preset_validators.wlan_validator import WlanPresetValidator
from application.psd_unit_policy import PSD_ALLOWED_UNITS, normalize_psd_result_unit
from application.test_type_symbols import normalize_profile_name, normalize_test_type_list
from domain.ruleset_models import collect_ruleset_test_types, project_ruleset_test_contracts
from domain.test_item_pool import get_test_item_definition


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
        self._registry = PresetValidatorRegistry()
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
        if not has_wlan_expansion and not sel.bandwidth_mhz:
            result.add_error("At least one bandwidth is required.")
        if not has_wlan_expansion and not sel.channels.channels:
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

        normalized_tests = normalize_test_type_list(sel.test_types)
        normalized_order = normalize_test_type_list(sel.execution_policy.test_order)
        ruleset_payload = _load_ruleset_payload(model.ruleset_id)
        migration = analyze_preset_model(model, ruleset_payload)

        for message in migration.auto_fixes:
            result.add_warning(f"Auto-fix available at runtime: {message}")
        for item in migration.disabled_items:
            result.add_warning(f"Disabled in effective preset: {item.value} ({item.reason})")
        for message in migration.warnings:
            result.add_warning(message)
        for message in migration.errors:
            result.add_warning(f"Execution blocked until fixed: {message}")

        duplicated_tests = _find_duplicates(normalized_tests)
        if duplicated_tests:
            result.add_warning(f"Duplicate test types found: {duplicated_tests}")

        effective_tests = normalize_test_type_list(migration.effective_selection.get("test_types") or normalized_tests)
        for test_type in effective_tests:
            pool_item = get_test_item_definition(test_type) or {}
            required_instruments = [
                str(item).strip()
                for item in (pool_item.get("required_instruments") or [])
                if str(item).strip()
            ]
            if required_instruments:
                result.add_warning(
                    f"Test '{test_type}' requires instruments: {', '.join(required_instruments)}. "
                    "Verify equipment/instrument profile coverage before execution."
                )

        missing_exec = [tt for tt in effective_tests if tt not in normalized_order]
        if missing_exec:
            result.add_warning(
                f"Execution order does not include selected/effective test types: {missing_exec}. "
                "Effective preset will append them automatically at execution time."
            )

        measurement_profile_name = normalize_profile_name(sel.measurement_profile_name)
        if measurement_profile_name:
            conflicting = sorted({
                normalize_profile_name(name)
                for name in sel.instrument_profile_by_test.values()
                if normalize_profile_name(name) and normalize_profile_name(name) != measurement_profile_name
            })
            if conflicting:
                result.add_warning(
                    "Measurement Profile selector differs from per-test Instrument Profiles JSON. "
                    f"Selector={measurement_profile_name}, per-test={conflicting}"
                )

        psd_result_unit = normalize_psd_result_unit(getattr(sel, "psd_result_unit", ""))
        if getattr(sel, "psd_result_unit", "") and psd_result_unit not in PSD_ALLOWED_UNITS:
            result.add_error(
                f"Unsupported PSD result unit: {sel.psd_result_unit}. Allowed: {sorted(PSD_ALLOWED_UNITS)}"
            )

        nominal_voltage_v = getattr(sel, "nominal_voltage_v", None)
        if nominal_voltage_v not in (None, ""):
            try:
                if float(nominal_voltage_v) <= 0:
                    result.add_error("Nominal voltage must be greater than 0 V.")
            except Exception:
                result.add_error("Nominal voltage must be a valid number.")
        if "KC" in str(model.ruleset_id or "").upper() and nominal_voltage_v in (None, ""):
            result.add_warning("KC preset is missing nominal voltage. Voltage condition axis will be skipped.")

        extension_validators = self._registry.resolve_validators(model)
        if extension_validators:
            for validator in extension_validators:
                validator.validate(model, result)
        elif _looks_like_wlan(model):
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


def _load_ruleset_payload(ruleset_id: str) -> dict:
    normalized = str(ruleset_id or "").strip()
    if not normalized:
        return {}
    path = Path("rulesets") / f"{normalized.lower()}.json"
    if not path.exists() and normalized.upper() == "KC_WLAN":
        alt = Path("rulesets") / "kc_wlan.json"
        if alt.exists():
            path = alt
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["test_contracts"] = project_ruleset_test_contracts(
            payload.get("test_contracts") or {},
            tests_supported=collect_ruleset_test_types(payload),
        )
        return payload
    except Exception:
        return {}
