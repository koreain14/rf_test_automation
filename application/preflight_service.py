from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from application.correction_profile_loader import CorrectionProfileLoader
from application.correction_runtime import normalize_correction_meta, resolve_bound_path
from application.device_registry import DeviceRegistry
from application.equipment_profile_repo import EquipmentProfileRepo
from application.instrument_factory import AutoInstrumentFactory, DummyInstrumentFactory, ScpiInstrumentFactory
from application.instrument_manager import InstrumentManager


@dataclass
class PreflightIssue:
    code: str
    message: str
    level: str = "ERROR"


@dataclass
class PreflightResult:
    issues: List[PreflightIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.level.upper() == "ERROR" for issue in self.issues)

    def add_error(self, code: str, message: str) -> None:
        self.issues.append(PreflightIssue(code=code, message=message, level="ERROR"))

    def add_warning(self, code: str, message: str) -> None:
        self.issues.append(PreflightIssue(code=code, message=message, level="WARNING"))

    def first_error(self) -> str:
        for issue in self.issues:
            if issue.level.upper() == "ERROR":
                return issue.message
        return ""

    def summary(self) -> str:
        if not self.issues:
            return "OK"
        return "\n".join(f"[{issue.level}] {issue.message}" for issue in self.issues)

class PreflightService:
    """Application service for run-time preflight validation."""

    def __init__(
        self,
        device_registry: DeviceRegistry,
        profile_repo: EquipmentProfileRepo,
        instrument_manager: InstrumentManager | None = None,
    ):
        self.device_registry = device_registry
        self.profile_repo = profile_repo
        self.instrument_manager = instrument_manager
        self.correction_loader = CorrectionProfileLoader()

    def validate_plan_context(self, plan_ctx: Any, equipment_profile_name: Optional[str]) -> PreflightResult:
        result = PreflightResult()

        if plan_ctx is None:
            result.add_error("PLAN_MISSING", "Selected plan context not found.")
            return result

        if not equipment_profile_name:
            return self._validate_profileless_plan_context(plan_ctx, result)

        profile = self.profile_repo.get_profile(equipment_profile_name)
        if not profile:
            result.add_error("PROFILE_NOT_FOUND", f"Equipment profile not found: {equipment_profile_name}")
            return result

        recipe = getattr(plan_ctx, 'recipe', None)
        meta = getattr(recipe, 'meta', None) or {}
        rf_path = meta.get('rf_path') or {}
        power_control = meta.get('power_control') or {}
        motion_control = meta.get('motion_control') or {}
        correction = normalize_correction_meta(meta)

        self._validate_device_slot(result, getattr(profile, 'analyzer', None), 'analyzer', 'Analyzer', required=True)

        switch_path = rf_path.get('switch_path')
        if switch_path:
            self._validate_device_slot(result, getattr(profile, 'switchbox', None), 'switchbox', 'Switchbox', required=True)
            self._validate_switch_path(result, getattr(profile, 'switchbox', None), str(switch_path))

        if bool(power_control.get('enabled')):
            self._validate_device_slot(result, getattr(profile, 'power_supply', None), 'power_supply', 'Power supply', required=True)
            self._validate_float(result, 'POWER_VOLTAGE_INVALID', 'Power voltage must be a valid number.', power_control.get('voltage'))
            self._validate_float(result, 'POWER_CURRENT_INVALID', 'Power current limit must be a valid number.', power_control.get('current_limit'))

        if bool(motion_control.get('enabled')):
            angle = motion_control.get('turntable_angle_deg')
            height = motion_control.get('mast_height_cm')
            if angle not in (None, ''):
                self._validate_device_slot(result, getattr(profile, 'turntable', None), 'turntable', 'Turntable', required=True)
                self._validate_float(result, 'MOTION_ANGLE_INVALID', 'Turntable angle must be a valid number.', angle)
            if height not in (None, ''):
                self._validate_device_slot(result, getattr(profile, 'mast', None), 'mast', 'Mast', required=True)
                self._validate_float(result, 'MOTION_HEIGHT_INVALID', 'Mast height must be a valid number.', height)

        self._validate_correction(result, meta)
        return result

    def validate_scenario(self, plan_contexts: list[Any], equipment_profile_name: Optional[str]) -> PreflightResult:
        result = PreflightResult()
        if not plan_contexts:
            result.add_error('SCENARIO_EMPTY', 'No plans found in the scenario.')
            return result

        for idx, ctx in enumerate(plan_contexts, start=1):
            sub = self.validate_plan_context(ctx, equipment_profile_name)
            for issue in sub.issues:
                result.issues.append(
                    PreflightIssue(code=issue.code, level=issue.level, message=f"Plan #{idx}: {issue.message}")
                )
        return result

    def runtime_factory_mode(self) -> str:
        factory = getattr(self.instrument_manager, "factory", None)
        if isinstance(factory, DummyInstrumentFactory):
            return "DUMMY"
        if isinstance(factory, ScpiInstrumentFactory):
            return "SCPI"
        if isinstance(factory, AutoInstrumentFactory):
            return "AUTO"
        return "UNKNOWN"

    def allows_profileless_run(self) -> bool:
        return self.runtime_factory_mode() == "DUMMY"

    def _validate_profileless_plan_context(self, plan_ctx: Any, result: PreflightResult) -> PreflightResult:
        recipe = getattr(plan_ctx, "recipe", None)
        meta = getattr(recipe, "meta", None) or {}
        rf_path = meta.get("rf_path") or {}
        power_control = meta.get("power_control") or {}
        motion_control = meta.get("motion_control") or {}
        correction = normalize_correction_meta(meta)

        if not self.allows_profileless_run():
            mode = self.runtime_factory_mode()
            if mode == "AUTO":
                result.add_error(
                    "PROFILE_MISSING",
                    "Select an equipment profile before running. Profile-less execution is only allowed in explicit DUMMY mode.",
                )
            elif mode == "SCPI":
                result.add_error(
                    "PROFILE_MISSING",
                    "Select an equipment profile before running. SCPI mode requires an equipment profile.",
                )
            else:
                result.add_error(
                    "PROFILE_MISSING",
                    "Select an equipment profile before running.",
                )
            return result

        if rf_path.get("switch_path"):
            result.add_error(
                "SWITCHBOX_PROFILE_REQUIRED",
                "Switch path control requires an equipment profile with a configured switchbox.",
            )

        if bool(power_control.get("enabled")):
            result.add_error(
                "POWER_PROFILE_REQUIRED",
                "Power control requires an equipment profile with a configured power supply.",
            )

        angle = motion_control.get("turntable_angle_deg")
        height = motion_control.get("mast_height_cm")
        if bool(motion_control.get("enabled")) or angle not in (None, "") or height not in (None, ""):
            result.add_error(
                "MOTION_PROFILE_REQUIRED",
                "Motion control requires an equipment profile with configured motion devices.",
            )

        if correction.get("enabled"):
            self._validate_correction(result, meta)

        if result.ok:
            result.add_warning(
                "PROFILELESS_DUMMY_RUN",
                "Running without an equipment profile in DUMMY mode. Analyzer execution uses the dummy measurement path only.",
            )

        return result

    def _validate_device_slot(self, result: PreflightResult, profile_device_name: Optional[str], expected_type: str, role_label: str, required: bool) -> None:
        if not profile_device_name:
            if required:
                result.add_error(f"{expected_type.upper()}_MISSING", f"{role_label} is required by the current plan, but not configured in the equipment profile.")
            return

        device = self.device_registry.get_device(profile_device_name)
        if not device:
            result.add_error(f"{expected_type.upper()}_NOT_FOUND", f"{role_label} device not found in registry: {profile_device_name}")
            return

        if device.type != expected_type:
            result.add_error(
                f"{expected_type.upper()}_TYPE_MISMATCH",
                f"{role_label} binding mismatch: '{profile_device_name}' is type '{device.type}', expected '{expected_type}'.",
            )

    def _validate_switch_path(self, result: PreflightResult, switchbox_name: Optional[str], switch_path: str) -> None:
        if not switchbox_name:
            return
        device = self.device_registry.get_device(switchbox_name)
        if not device:
            return
        path_names = [str(p.get('name', '')) for p in (device.ports or []) if isinstance(p, dict) and p.get('name')]
        if path_names and switch_path not in path_names:
            result.add_error('SWITCH_PATH_INVALID', f"Switch path '{switch_path}' not found in switchbox '{switchbox_name}'. Available: {path_names}")


    def _validate_correction(self, result: PreflightResult, meta: dict) -> None:
        correction = normalize_correction_meta(meta)
        if not correction.get("enabled"):
            return
        storage_kind = str(correction.get("storage_kind") or "")
        if storage_kind == "instrument_factor":
            mode = str(correction.get("mode") or "instrument").strip().lower()
            if mode not in {"instrument", "off"}:
                result.add_error("CORRECTION_MODE_INVALID", f"Unsupported correction mode: {mode}")
                return
            manual_override = dict(correction.get("manual_override") or {})
            apply_model = str(correction.get("apply_model") or "auto").strip().lower()
            if apply_model not in {"auto", "manual"}:
                result.add_error("CORRECTION_APPLY_MODEL_INVALID", f"Unsupported correction apply model: {apply_model}")
            if mode == "instrument" and (manual_override.get("enabled") or apply_model == "manual"):
                set_id = str(manual_override.get("set_id") or "").strip()
                if not set_id:
                    result.add_error(
                        "CORRECTION_MANUAL_SET_MISSING",
                        "Manual Override is selected, but no Correction Set / Factor Group is specified.",
                    )
            return

        mode = str(correction.get("mode") or "DIRECT").strip().upper()
        if mode not in {"DIRECT", "SWITCH"}:
            result.add_error("CORRECTION_MODE_INVALID", f"Unsupported correction mode: {mode}")
            return
        profile_name = str(correction.get("profile_name") or "").strip()
        if not profile_name:
            result.add_error("CORRECTION_PROFILE_MISSING", "Correction is enabled but no correction profile is selected.")
            return
        profile = self.correction_loader.get_profile(profile_name)
        if profile is None:
            result.add_error("CORRECTION_PROFILE_NOT_FOUND", f"Correction profile not found: {profile_name}")
            return
        if profile.normalized_mode() != mode:
            result.add_error(
                "CORRECTION_PROFILE_MODE_MISMATCH",
                f"Correction profile '{profile_name}' is mode '{profile.normalized_mode()}', expected '{mode}'.",
            )
            return
        try:
            float(correction.get("manual_offset_db") or 0.0)
        except Exception:
            result.add_error("CORRECTION_OFFSET_INVALID", "Correction manual offset must be a valid number.")
        bound_path, binding_source = resolve_bound_path(meta, correction)
        if mode == "SWITCH":
            if not bound_path:
                result.add_error(
                    "CORRECTION_BOUND_PATH_MISSING",
                    "SWITCH correction requires an RF Path selection. Select Antenna or Switch Path before running.",
                )
                return
            if bound_path not in dict(profile.ports or {}):
                result.add_error(
                    "CORRECTION_BOUND_PATH_INVALID",
                    f"Correction bound path '{bound_path}' from {binding_source or 'rf_path'} is not present in correction profile '{profile_name}'.",
                )

    def _validate_float(self, result: PreflightResult, code: str, message: str, value: Any) -> None:
        if value in (None, ''):
            return
        try:
            float(value)
        except Exception:
            result.add_error(code, message)
