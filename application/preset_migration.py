from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from application.preset_model import PresetModel
from application.test_type_symbols import DEFAULT_TEST_ORDER, normalize_test_type_list, normalize_test_type_map
from domain.models import Preset, RuleSet
from domain.ruleset_models import normalize_data_rate_policy
from domain.test_item_pool import get_test_item_definition, is_selectable_test_item
from domain.test_item_registry import normalize_test_id


MIGRATION_STATUS_CLEAN = "clean"
MIGRATION_STATUS_WARNING = "warning"
MIGRATION_STATUS_INVALID = "invalid"


@dataclass(frozen=True)
class DisabledPresetItem:
    field: str
    value: str
    reason: str


@dataclass
class MigrationResult:
    status: str = MIGRATION_STATUS_CLEAN
    auto_fixes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disabled_items: list[DisabledPresetItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    effective_selection: dict[str, Any] = field(default_factory=dict)
    ruleset_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.errors)

    def finalize(self) -> "MigrationResult":
        if self.errors:
            self.status = MIGRATION_STATUS_INVALID
        elif self.warnings or self.disabled_items or self.auto_fixes:
            self.status = MIGRATION_STATUS_WARNING
        else:
            self.status = MIGRATION_STATUS_CLEAN
        return self


@dataclass(frozen=True)
class EffectivePreset:
    raw_preset: Preset
    effective_preset: Preset
    migration: MigrationResult


def build_effective_preset(raw_preset: Preset, ruleset: RuleSet) -> EffectivePreset:
    migration = reconcile_preset_selection(
        selection=raw_preset.selection,
        ruleset=ruleset,
    )
    effective_preset = Preset(
        name=raw_preset.name,
        ruleset_id=raw_preset.ruleset_id,
        ruleset_version=raw_preset.ruleset_version,
        selection=migration.effective_selection,
        description=raw_preset.description,
    )
    return EffectivePreset(
        raw_preset=raw_preset,
        effective_preset=effective_preset,
        migration=migration,
    )


def analyze_preset_model(model: PresetModel, ruleset_payload: Mapping[str, Any] | RuleSet | None) -> MigrationResult:
    selection = _selection_from_model(model)
    return reconcile_preset_selection(selection=selection, ruleset=ruleset_payload)


def summarize_migration_result(migration: MigrationResult) -> str:
    lines = [f"status={migration.status}"]
    if migration.auto_fixes:
        lines.append("auto_fixes=" + "; ".join(migration.auto_fixes))
    if migration.disabled_items:
        lines.append(
            "disabled="
            + "; ".join(f"{item.field}:{item.value} ({item.reason})" for item in migration.disabled_items)
        )
    if migration.warnings:
        lines.append("warnings=" + "; ".join(migration.warnings))
    if migration.errors:
        lines.append("errors=" + "; ".join(migration.errors))
    effective_tests = normalize_test_type_list(migration.effective_selection.get("test_types") or [])
    lines.append("effective_tests=" + (", ".join(effective_tests) if effective_tests else "(none)"))
    return " | ".join(lines)


def reconcile_preset_selection(
    *,
    selection: Mapping[str, Any] | None,
    ruleset: Mapping[str, Any] | RuleSet | None,
) -> MigrationResult:
    raw_selection = deepcopy(dict(selection or {}))
    effective_selection = deepcopy(raw_selection)
    migration = MigrationResult(
        effective_selection=effective_selection,
        ruleset_meta={
            "ruleset_id": _ruleset_value(ruleset, "id"),
            "ruleset_version": _ruleset_value(ruleset, "version"),
            "ruleset_tech": _ruleset_value(ruleset, "tech"),
        },
    )

    raw_test_types = list(raw_selection.get("test_types") or [])
    normalized_tests, auto_fixes = _normalize_test_ids_with_messages(raw_test_types, field_name="selection.test_types")
    migration.auto_fixes.extend(auto_fixes)
    effective_selection["test_types"] = list(normalized_tests)

    execution_policy = dict(raw_selection.get("execution_policy") or {})
    raw_test_order = list(execution_policy.get("test_order") or [])
    normalized_order, order_fixes = _normalize_test_ids_with_messages(raw_test_order, field_name="selection.execution_policy.test_order")
    migration.auto_fixes.extend(order_fixes)

    raw_profile_map = dict(raw_selection.get("instrument_profile_by_test") or {})
    normalized_profile_map, profile_fixes = _normalize_test_id_map_with_messages(
        raw_profile_map,
        field_name="selection.instrument_profile_by_test",
    )
    migration.auto_fixes.extend(profile_fixes)

    ruleset_tech = str(_ruleset_value(ruleset, "tech") or "").strip().upper()
    ruleset_bands = _ruleset_bands(ruleset)
    selected_band = str(raw_selection.get("band", "") or "").strip()
    band_payload = ruleset_bands.get(selected_band)
    band_allowed_tests = _band_allowed_tests(band_payload)
    ruleset_declared_tests = _ruleset_declared_tests(ruleset)

    if ruleset and selected_band and band_payload is None:
        migration.errors.append(
            f"Preset band '{selected_band}' is no longer defined by the current RuleSet."
        )

    effective_tests: list[str] = []
    for test_id in normalized_tests:
        pool_item = get_test_item_definition(test_id)
        if pool_item is None:
            migration.disabled_items.append(
                DisabledPresetItem(
                    field="test_types",
                    value=test_id,
                    reason="No longer defined in the Global Test Item Pool.",
                )
            )
            continue
        if ruleset_declared_tests and test_id not in ruleset_declared_tests:
            migration.disabled_items.append(
                DisabledPresetItem(
                    field="test_types",
                    value=test_id,
                    reason="No longer declared by the current RuleSet.",
                )
            )
            continue
        if band_payload is not None and band_allowed_tests and test_id not in band_allowed_tests:
            migration.disabled_items.append(
                DisabledPresetItem(
                    field="test_types",
                    value=test_id,
                    reason=f"Not supported for band '{selected_band}' in the current RuleSet.",
                )
            )
            continue
        if not is_selectable_test_item(test_id, tech=ruleset_tech):
            migration.disabled_items.append(
                DisabledPresetItem(
                    field="test_types",
                    value=test_id,
                    reason="Not currently executable for the active RuleSet tech/procedure registry.",
                )
            )
            continue
        effective_tests.append(test_id)

    effective_selection["test_types"] = list(effective_tests)
    effective_selection["execution_policy"] = _build_effective_execution_policy(
        raw_policy=execution_policy,
        normalized_order=normalized_order,
        effective_tests=effective_tests,
    )
    effective_selection["instrument_profile_by_test"] = {
        test_id: profile_name
        for test_id, profile_name in normalized_profile_map.items()
        if test_id in effective_tests
    }

    disabled_test_ids = {item.value for item in migration.disabled_items if item.field == "test_types"}
    if disabled_test_ids:
        disabled_text = ", ".join(sorted(disabled_test_ids))
        migration.warnings.append(
            f"Disabled test items retained in raw preset and excluded from execution: {disabled_text}."
        )

    if raw_test_types and not effective_tests:
        migration.errors.append(
            "No executable test items remain after reconciling the preset with the current RuleSet."
        )

    _validate_standard_and_wlan_expansion(
        migration=migration,
        raw_selection=raw_selection,
        ruleset=ruleset,
        selected_band=selected_band,
        band_payload=band_payload,
    )
    _validate_selected_data_rates(
        migration=migration,
        raw_selection=raw_selection,
        ruleset=ruleset,
    )

    return migration.finalize()


def _selection_from_model(model: PresetModel) -> dict[str, Any]:
    return asdict(model.selection)


def _normalize_test_ids_with_messages(values: list[Any], *, field_name: str) -> tuple[list[str], list[str]]:
    out: list[str] = []
    fixes: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        raw = str(value or "").strip()
        normalized = normalize_test_id(raw)
        if not raw:
            continue
        if normalized and normalized != raw:
            fixes.append(f"{field_name}: '{raw}' -> '{normalized}'")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out, fixes


def _normalize_test_id_map_with_messages(
    values: Mapping[str, Any],
    *,
    field_name: str,
) -> tuple[dict[str, str], list[str]]:
    out: dict[str, str] = {}
    fixes: list[str] = []
    for raw_key, raw_value in dict(values or {}).items():
        normalized_key = normalize_test_id(raw_key)
        if not normalized_key:
            continue
        if normalized_key != str(raw_key or "").strip():
            fixes.append(f"{field_name}: '{raw_key}' -> '{normalized_key}'")
        out[normalized_key] = str(raw_value or "").strip()
    return out, fixes


def _build_effective_execution_policy(
    *,
    raw_policy: Mapping[str, Any],
    normalized_order: list[str],
    effective_tests: list[str],
) -> dict[str, Any]:
    ordered = [test_id for test_id in normalized_order if test_id in effective_tests]
    for test_id in effective_tests:
        if test_id not in ordered:
            ordered.append(test_id)
    return {
        "type": str(raw_policy.get("type", "CHANNEL_CENTRIC") or "CHANNEL_CENTRIC").strip() or "CHANNEL_CENTRIC",
        "test_order": ordered or [test_id for test_id in DEFAULT_TEST_ORDER if test_id in effective_tests],
        "include_bw_in_group": bool(raw_policy.get("include_bw_in_group", True)),
    }


def _validate_standard_and_wlan_expansion(
    *,
    migration: MigrationResult,
    raw_selection: Mapping[str, Any],
    ruleset: Mapping[str, Any] | RuleSet | None,
    selected_band: str,
    band_payload: Any,
) -> None:
    if not ruleset or band_payload is None:
        return

    supported_standards = _band_standards(band_payload)
    wlan_expansion = dict(raw_selection.get("wlan_expansion") or {})
    mode_plan = list(wlan_expansion.get("mode_plan") or [])
    if mode_plan:
        invalid_standards = []
        for item in mode_plan:
            standard = str(item.get("standard", item.get("mode", "")) or "").strip()
            if standard and standard not in supported_standards and standard not in invalid_standards:
                invalid_standards.append(standard)
        if invalid_standards:
            migration.errors.append(
                f"WLAN expansion includes standards not supported in band '{selected_band}': {invalid_standards}."
            )
        return

    standard = str(raw_selection.get("standard", "") or "").strip()
    if standard and standard not in supported_standards:
        migration.errors.append(
            f"Preset standard '{standard}' is not supported in band '{selected_band}' by the current RuleSet."
        )


def _validate_selected_data_rates(
    *,
    migration: MigrationResult,
    raw_selection: Mapping[str, Any],
    ruleset: Mapping[str, Any] | RuleSet | None,
) -> None:
    selected_data_rates = []
    for item in list(raw_selection.get("selected_data_rates") or []):
        rate = str(item or "").strip().upper()
        if rate and rate not in selected_data_rates:
            selected_data_rates.append(rate)
    migration.effective_selection["selected_data_rates"] = list(selected_data_rates)
    if not selected_data_rates:
        return

    policy = normalize_data_rate_policy(_ruleset_value(ruleset, "data_rate_policy") or {})
    if not bool(policy.get("enabled")):
        migration.warnings.append(
            f"Selected data rates are stored, but the current RuleSet data-rate axis is disabled: {selected_data_rates}."
        )
        return

    standards = _selected_standards(raw_selection)
    if not standards:
        return

    allowed_union: set[str] = set()
    by_standard = dict(policy.get("by_standard") or {})
    for standard in standards:
        for rate in list(by_standard.get(standard) or []):
            name = str(rate or "").strip().upper()
            if name:
                allowed_union.add(name)
    invalid_rates = [rate for rate in selected_data_rates if allowed_union and rate not in allowed_union]
    if invalid_rates:
        migration.errors.append(
            f"Selected data rates are not supported by the current RuleSet selection: {invalid_rates}."
        )


def _selected_standards(selection: Mapping[str, Any]) -> list[str]:
    wlan_expansion = dict(selection.get("wlan_expansion") or {})
    mode_plan = list(wlan_expansion.get("mode_plan") or [])
    out: list[str] = []
    if mode_plan:
        for item in mode_plan:
            standard = str(item.get("standard", item.get("mode", "")) or "").strip()
            if standard and standard not in out:
                out.append(standard)
        return out

    standard = str(selection.get("standard", "") or "").strip()
    return [standard] if standard else []


def _ruleset_value(ruleset: Mapping[str, Any] | RuleSet | None, key: str) -> Any:
    if ruleset is None:
        return None
    if isinstance(ruleset, Mapping):
        return ruleset.get(key)
    return getattr(ruleset, key, None)


def _ruleset_bands(ruleset: Mapping[str, Any] | RuleSet | None) -> dict[str, Any]:
    bands = _ruleset_value(ruleset, "bands") or {}
    return dict(bands)


def _ruleset_declared_tests(ruleset: Mapping[str, Any] | RuleSet | None) -> list[str]:
    out: list[str] = []
    for band_payload in _ruleset_bands(ruleset).values():
        for test_id in _band_allowed_tests(band_payload):
            if test_id not in out:
                out.append(test_id)
    return out


def _band_allowed_tests(band_payload: Any) -> list[str]:
    if band_payload is None:
        return []
    raw = getattr(band_payload, "tests_supported", None)
    if raw is None and isinstance(band_payload, Mapping):
        raw = band_payload.get("tests_supported")
    return normalize_test_type_list(raw or [])


def _band_standards(band_payload: Any) -> list[str]:
    if band_payload is None:
        return []
    raw = getattr(band_payload, "standards", None)
    if raw is None and isinstance(band_payload, Mapping):
        raw = band_payload.get("standards")
    return [str(item).strip() for item in (raw or []) if str(item).strip()]
