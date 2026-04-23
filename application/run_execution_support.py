from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from application.correction_profile_loader import CorrectionProfileLoader
from application.correction_runtime import (
    apply_correction_to_result,
    format_correction_summary,
    normalize_correction_meta,
    resolve_runtime_correction,
)
from application.execution_builder import ExecutionBuilder
from application.executor_factory import ExecutorFactory
from application.instrument_manager import InstrumentManager
from application.instrument_profile_resolver import InstrumentProfileResolver
from application.procedures import ProcedureRegistry
from application.runner_step import StepRunner
from application.step_sink_sqlite import StepResultSinkSQLite
from application.test_type_symbols import normalize_test_type_symbol
from domain.execution import RunContext
from domain.expand import expand_recipe
from domain.overrides import apply_overrides
from infrastructure.run_repo_sqlite import RunRepositorySQLite


log = logging.getLogger(__name__)


def _normalize_correction_factor_no(value: Any) -> int | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    if text.startswith("CSET"):
        text = text[4:].strip()
    if not text.isdigit():
        return None
    number = int(text)
    return number if number > 0 else None


def _correction_cset_command(factor_no: int, enabled: bool) -> str:
    state = "ON" if enabled else "OFF"
    return f":SENS:CORR:CSET{int(factor_no)} {state}"


def _iter_scpi_write_targets(obj: Any):
    visited: set[int] = set()
    queue = [obj]
    while queue:
        current = queue.pop(0)
        if current is None:
            continue
        ident = id(current)
        if ident in visited:
            continue
        visited.add(ident)
        if callable(getattr(current, "write", None)):
            yield current
        for attr in ("driver", "instrument", "device", "resource", "session", "analyzer", "_session", "inst"):
            if not hasattr(current, attr):
                continue
            try:
                queue.append(getattr(current, attr))
            except Exception:
                pass


def _resolve_scpi_write_target(inst: Any):
    for target in _iter_scpi_write_targets(inst):
        return target
    return None


@dataclass
class RunEnvironment:
    session: Any
    instrument: Any
    run_metadata: dict[str, Any]
    power_control: dict[str, Any]
    motion_control: dict[str, Any]
    dut_control_mode: str
    switch_path: str | None
    antenna: str | None


class RunSessionCoordinator:
    def __init__(self, instrument_manager: InstrumentManager):
        self.instrument_manager = instrument_manager

    def get_dut_control_mode(self, recipe) -> str:
        meta = ((recipe.meta or {}) if recipe else {})
        mode = str(meta.get("dut_control_mode") or "manual").strip().lower()
        if mode not in {"manual", "auto_license", "auto_callbox"}:
            return "manual"
        return mode

    def prepare_environment(self, *, equipment_profile_name: Optional[str], recipe) -> RunEnvironment:
        session = None
        power_control = (((recipe.meta or {}).get("power_control") or {}) if recipe else {})
        rf_path = (((recipe.meta or {}).get("rf_path") or {}) if recipe else {})
        switch_path = (rf_path.get("switch_path") if rf_path else None)
        antenna = (rf_path.get("antenna") if rf_path else None)
        motion_control = (((recipe.meta or {}).get("motion_control") or {}) if recipe else {})
        dut_control_mode = self.get_dut_control_mode(recipe)

        if equipment_profile_name:
            session = self.instrument_manager.create_session(equipment_profile_name)
            log.info(
                "session created | equipment_profile=%s devices=%s",
                equipment_profile_name,
                self._device_summary(session),
            )
            self._apply_session_controls(
                session=session,
                equipment_profile_name=equipment_profile_name,
                switch_path=switch_path,
                power_control=power_control,
                motion_control=motion_control,
            )

        instrument = getattr(session, "analyzer", None) if session is not None else None
        if instrument is None:
            instrument = self.instrument_manager.get_measurement_instrument()
            log.info("session analyzer missing -> fallback instrument=%s", type(instrument).__name__)
            run_meta = self.instrument_manager.build_session_metadata(
                equipment_profile_name=equipment_profile_name,
                session=session,
                fallback_instrument=instrument,
            )
        else:
            log.info("session analyzer selected -> instrument=%s", type(instrument).__name__)
            run_meta = self.instrument_manager.build_session_metadata(
                equipment_profile_name=equipment_profile_name,
                session=session,
                fallback_instrument=None,
            )

        if switch_path:
            run_meta["switch_path"] = switch_path
        if antenna:
            run_meta["antenna"] = antenna
        if power_control:
            run_meta["power_control"] = dict(power_control)
        if motion_control:
            run_meta["motion_control"] = dict(motion_control)
        run_meta["dut_control_mode"] = dut_control_mode
        if recipe is not None:
            run_meta["measurement_profile_by_test"] = {
                str(test_type): str(getattr(profile, "name", "") or "")
                for test_type, profile in dict(getattr(recipe, "instrument_profile_by_test", {}) or {}).items()
            }
            run_meta["measurement_profile_source"] = "recipe.instrument_profile_by_test"
            correction = normalize_correction_meta(getattr(recipe, "meta", {}) or {})
            if correction.get("enabled"):
                run_meta["correction"] = correction
                run_meta["correction_text"] = format_correction_summary(getattr(recipe, "meta", {}) or {})

        return RunEnvironment(
            session=session,
            instrument=instrument,
            run_metadata=run_meta,
            power_control=dict(power_control),
            motion_control=dict(motion_control),
            dut_control_mode=dut_control_mode,
            switch_path=switch_path,
            antenna=antenna,
        )

    def cleanup(self, session, power_control: dict | None = None) -> None:
        if session is None:
            return
        power_output_off = bool((power_control or {}).get("enabled") and (power_control or {}).get("output_on"))
        if hasattr(session, "cleanup"):
            session.cleanup(power_output_off=power_output_off)
            return

        power_supply = getattr(session, "power_supply", None)
        if power_output_off and power_supply is not None and hasattr(power_supply, "output_off"):
            try:
                power_supply.output_off()
            except Exception:
                log.warning("power off failed during cleanup", exc_info=True)

        for attr in ("analyzer", "turntable", "mast", "switchbox", "power_supply"):
            dev = getattr(session, attr, None)
            if dev is not None and hasattr(dev, "disconnect"):
                try:
                    dev.disconnect()
                except Exception:
                    log.warning("disconnect failed during cleanup: %s", attr, exc_info=True)

    def _device_summary(self, session) -> dict:
        if session is None:
            return {}
        if hasattr(session, "summary"):
            return session.summary()
        summary = {}
        for attr in ("analyzer", "turntable", "mast", "switchbox", "power_supply"):
            dev = getattr(session, attr, None)
            summary[attr] = type(dev).__name__ if dev is not None else None
        return summary

    def _require_capability(self, device, attr_name: str, capability: str, equipment_profile_name: str | None) -> None:
        if device is None:
            raise RuntimeError(
                f"Required device '{attr_name}' is missing in equipment profile '{equipment_profile_name or '(none)'}'."
            )
        if not hasattr(device, capability):
            raise RuntimeError(
                f"Configured {attr_name} device is invalid: {type(device).__name__} "
                f"does not support '{capability}()'."
            )

    def _apply_session_controls(
        self,
        *,
        session,
        equipment_profile_name: str,
        switch_path: str | None,
        power_control: dict[str, Any],
        motion_control: dict[str, Any],
    ) -> None:
        if switch_path:
            switchbox = getattr(session, "switchbox", None)
            self._require_capability(switchbox, "switchbox", "select_path", equipment_profile_name)
            available = []
            if hasattr(switchbox, "list_paths"):
                try:
                    available = list(switchbox.list_paths())
                except Exception:
                    available = []
            if available and switch_path not in available:
                raise RuntimeError(
                    f"Switch path '{switch_path}' not found in switchbox. Available: {available}"
                )
            switchbox.select_path(switch_path)
            log.info(
                "switch path selected | equipment_profile=%s path=%s switchbox=%s",
                equipment_profile_name,
                switch_path,
                type(switchbox).__name__,
            )

        if power_control.get("enabled"):
            power_supply = getattr(session, "power_supply", None)
            self._require_capability(power_supply, "power_supply", "disconnect", equipment_profile_name)

            voltage = power_control.get("voltage")
            current_limit = power_control.get("current_limit")
            output_on = bool(power_control.get("output_on", False))

            if voltage not in (None, "") and hasattr(power_supply, "set_voltage"):
                power_supply.set_voltage(float(voltage))
            if current_limit not in (None, "") and hasattr(power_supply, "set_current_limit"):
                power_supply.set_current_limit(float(current_limit))
            if output_on:
                self._require_capability(power_supply, "power_supply", "output_on", equipment_profile_name)
                power_supply.output_on()

            log.info(
                "power settings applied | equipment_profile=%s voltage=%s current_limit=%s output_on=%s power_supply=%s",
                equipment_profile_name,
                voltage,
                current_limit,
                output_on,
                type(power_supply).__name__,
            )

        if motion_control.get("enabled"):
            turntable = getattr(session, "turntable", None)
            mast = getattr(session, "mast", None)
            angle = motion_control.get("turntable_angle_deg")
            height = motion_control.get("mast_height_cm")

            if turntable is not None and angle not in (None, "") and hasattr(turntable, "move_to"):
                try:
                    turntable.move_to(float(angle))
                    log.info(
                        "turntable move applied | equipment_profile=%s angle_deg=%s driver=%s",
                        equipment_profile_name,
                        angle,
                        type(turntable).__name__,
                    )
                except Exception as exc:
                    log.warning("turntable move skipped/failed | angle=%s error=%s", angle, exc)
            else:
                log.info("turntable move skipped | no configured/connected turntable")

            if mast is not None and height not in (None, "") and hasattr(mast, "move_to"):
                try:
                    mast.move_to(float(height))
                    log.info(
                        "mast move applied | equipment_profile=%s height_cm=%s driver=%s",
                        equipment_profile_name,
                        height,
                        type(mast).__name__,
                    )
                except Exception as exc:
                    log.warning("mast move skipped/failed | height=%s error=%s", height, exc)
            else:
                log.info("mast move skipped | no configured/connected mast")


class RunMetadataRecorder:
    def __init__(
        self,
        run_repo: RunRepositorySQLite,
        execution_builder: ExecutionBuilder,
        instrument_profile_resolver: InstrumentProfileResolver,
    ):
        self.run_repo = run_repo
        self.execution_builder = execution_builder
        self.instrument_profile_resolver = instrument_profile_resolver

    def update_run_metadata(self, *, run_id: str, metadata: dict[str, Any]) -> None:
        try:
            self.run_repo.update_run_metadata(run_id=run_id, metadata=metadata)
            log.info("run metadata saved | run=%s meta=%s", run_id, metadata)
        except Exception:
            log.warning("run metadata save skipped", exc_info=True)

    def create_result_stub(self, *, project_id: str, run_id: str, case, ruleset) -> str:
        return self.run_repo.create_result_stub(
            project_id=project_id,
            run_id=run_id,
            row={
                "test_key": case.key,
                "tech": ruleset.tech,
                "regulation": ruleset.regulation,
                "band": case.band,
                "standard": case.standard,
                "test_type": case.test_type,
                "channel": case.channel,
                "bw_mhz": case.bw_mhz,
                "instrument_snapshot": case.instrument,
                "tags": case.tags,
            },
        )

    def record_case_artifacts(
        self,
        *,
        project_id: str,
        preset_id: str,
        run_id: str,
        result_id: str,
        recipe,
        case,
        ruleset,
    ) -> None:
        try:
            self._record_run_context(result_id=result_id, recipe=recipe, project_id=project_id)
        except Exception:
            log.warning("run-context record failed for case=%s", case.key, exc_info=True)
        try:
            self._record_execution_step_model(
                result_id=result_id,
                case=case,
                ruleset=ruleset,
                run_id=run_id,
                project_id=project_id,
            )
        except Exception:
            log.warning("execution-model record failed for case=%s", case.key, exc_info=True)
        try:
            self._record_executor_preview(
                result_id=result_id,
                case=case,
                ruleset=ruleset,
                run_id=run_id,
                project_id=project_id,
                preset_id=preset_id,
            )
        except Exception:
            log.warning("executor-preview record failed for case=%s", case.key, exc_info=True)

    def update_final_result(self, *, result_id: str, values: dict[str, Any]) -> str:
        verdict = values.get("verdict", "ERROR")
        self.run_repo.update_result_final(
            result_id=result_id,
            status=verdict if verdict in ("PASS", "FAIL", "SKIP", "ERROR") else "ERROR",
            margin_db=values.get("margin_db"),
            measured_value=values.get("measured_value"),
            limit_value=values.get("limit_value"),
        )
        return verdict

    def _append_bridge_step_result(
        self,
        *,
        project_id: str,
        result_id: str,
        step_name: str,
        status: str,
        data: dict[str, Any],
    ) -> None:
        self.run_repo.append_step_result(
            project_id=project_id,
            result_id=result_id,
            step_name=step_name,
            status=status,
            data=data,
        )

    def _build_execution_case_payload(self, case, ruleset) -> dict[str, Any]:
        instrument_snapshot = dict(case.instrument or {})
        profile_name = str(
            instrument_snapshot.get("profile_name")
            or dict(case.tags or {}).get("measurement_profile_name")
            or ""
        )
        return {
            "id": case.key,
            "case_id": case.key,
            "key": case.key,
            "technology": getattr(ruleset, "tech", "WLAN"),
            "ruleset_id": getattr(ruleset, "id", ""),
            "band": case.band,
            "standard": case.standard,
            "phy_mode": case.tags.get("phy_mode", ""),
            "bandwidth_mhz": case.bw_mhz,
            "channel": case.channel,
            "frequency_mhz": case.center_freq_mhz,
            "test_type": case.test_type,
            "instrument_profile_name": profile_name,
            "instrument": instrument_snapshot,
            "tags": dict(case.tags or {}),
        }

    def _build_execution_steps(self, case, ruleset, run_id: str):
        payload = self._build_execution_case_payload(case, ruleset)
        return self.execution_builder.build_steps_for_case(run_id, payload)

    def _record_execution_step_model(self, result_id: str, case, ruleset, run_id: str, project_id: str) -> None:
        steps = self._build_execution_steps(case, ruleset, run_id)
        data = {
            "case_key": case.key,
            "standard": case.standard,
            "test_type": case.test_type,
            "step_count": len(steps),
            "steps": [
                {
                    "step_id": s.step_id,
                    "step_type": s.step_type,
                    "test_type": s.test_type,
                    "profile_name": s.instrument_profile_name,
                    "required_capabilities": list(s.required_capabilities),
                    "channel": s.channel,
                    "bandwidth_mhz": s.bandwidth_mhz,
                    "frequency_mhz": s.frequency_mhz,
                }
                for s in steps
            ],
        }
        self._append_bridge_step_result(
            project_id=project_id,
            result_id=result_id,
            step_name="EXECUTION_MODEL",
            status="OK",
            data=data,
        )

    def _record_run_context(self, result_id: str, recipe, project_id: str) -> None:
        data = dict((recipe.meta or {})) if recipe else {}
        data.setdefault("_display", {})["execution_policy"] = (data.get("execution_policy") or {})
        data.setdefault("_display", {})["ordering_policy"] = (data.get("ordering_policy") or {})
        self._append_bridge_step_result(
            project_id=project_id,
            result_id=result_id,
            step_name="RUN_CONTEXT",
            status="INFO",
            data=data,
        )

    def _record_executor_preview(self, result_id: str, case, ruleset, run_id: str, project_id: str, preset_id: str) -> None:
        steps = self._build_execution_steps(case, ruleset, run_id)
        preview_items = []
        ctx = RunContext(run_id=run_id, project_id=project_id, preset_id=preset_id, dry_run=True)
        for step in steps:
            item = {
                "step_id": step.step_id,
                "step_type": step.step_type,
                "test_type": step.test_type,
                "profile_name": step.instrument_profile_name,
            }
            try:
                resolved = self.instrument_profile_resolver.resolve_for_test_type(
                    step.instrument_profile_name,
                    step.test_type,
                )
                step.metadata["resolved_profile"] = resolved
                item["resolved_profile_name"] = resolved.get("profile_name", step.instrument_profile_name)
                item["resolved_profile_source"] = resolved.get("profile_source", "")
                item["profile"] = resolved
            except Exception as exc:
                item.update({"status": "PROFILE_ERROR", "message": str(exc)})
                preview_items.append(item)
                continue

            try:
                executor = ExecutorFactory.get_executor(step)
            except Exception as exc:
                item.update({"status": "NO_PREVIEW", "message": str(exc)})
                preview_items.append(item)
                continue

            try:
                result = executor.execute(step, ctx)
                item.update({"status": result.status, "message": result.message})
            except Exception as exc:
                item.update({"status": "ERROR", "message": str(exc)})
            preview_items.append(item)

        self._append_bridge_step_result(
            project_id=project_id,
            result_id=result_id,
            step_name="EXECUTOR_PREVIEW",
            status="OK",
            data={
                "case_key": case.key,
                "standard": case.standard,
                "test_type": case.test_type,
                "step_count": len(steps),
                "items": preview_items,
            },
        )


class VoltageConditionController:
    def __init__(self, run_repo: RunRepositorySQLite):
        self.run_repo = run_repo

    def apply_case_voltage(
        self,
        *,
        project_id: str,
        result_id: str,
        run_id: str,
        case,
        session,
        power_control: dict[str, Any] | None = None,
        equipment_profile_name: str | None = None,
    ) -> None:
        tags = dict(getattr(case, "tags", {}) or {})
        data = {
            "ruleset_id": tags.get("ruleset_id", ""),
            "voltage_policy_enabled": bool(tags.get("voltage_policy_enabled")),
            "voltage_policy_active": bool(tags.get("voltage_policy_active")),
            "voltage_policy_applied": bool(tags.get("voltage_policy_applied")),
            "voltage_policy_status": str(tags.get("voltage_policy_status", "") or ""),
            "voltage_policy_apply_to": list(tags.get("voltage_policy_apply_to") or []),
            "data_rate": str(tags.get("data_rate", "") or ""),
            "voltage_condition": str(tags.get("voltage_condition", "") or ""),
            "nominal_voltage_v": tags.get("nominal_voltage_v"),
            "target_voltage_v": tags.get("target_voltage_v"),
            "voltage_percent_offset": tags.get("voltage_percent_offset"),
            "voltage_settle_time_ms": int(tags.get("voltage_settle_time_ms", 0) or 0),
            "case_key": getattr(case, "key", ""),
            "test_type": getattr(case, "test_type", ""),
            "channel": getattr(case, "channel", ""),
            "bandwidth_mhz": getattr(case, "bw_mhz", ""),
            "equipment_profile_name": equipment_profile_name or "",
        }

        if not data["voltage_policy_enabled"]:
            return

        if not data["voltage_policy_active"] or not data["voltage_policy_applied"]:
            data["apply_status"] = "NOT_APPLICABLE"
            data["message"] = "Voltage policy is enabled but not applied to this test case."
            self._append_step_result(project_id=project_id, result_id=result_id, status="INFO", data=data)
            log.info(
                "case voltage skipped | run=%s case=%s test_type=%s status=%s apply_to=%s",
                run_id,
                getattr(case, "key", ""),
                getattr(case, "test_type", ""),
                data["voltage_policy_status"],
                data.get("voltage_policy_apply_to", []),
            )
            return

        target_voltage_v = self._as_float(data.get("target_voltage_v"))
        condition = str(data.get("voltage_condition", "") or "")
        power_supply = getattr(session, "power_supply", None) if session is not None else None

        if not condition or target_voltage_v is None:
            data["apply_status"] = "SKIPPED"
            data["message"] = "Voltage policy is enabled but case voltage metadata is inactive."
            self._append_step_result(project_id=project_id, result_id=result_id, status="INFO", data=data)
            log.warning(
                "case voltage skipped | run=%s case=%s status=%s nominal_voltage_v=%s condition=%s target_voltage_v=%s",
                run_id,
                getattr(case, "key", ""),
                data["voltage_policy_status"],
                data.get("nominal_voltage_v"),
                condition,
                data.get("target_voltage_v"),
            )
            return

        if power_supply is None:
            data["apply_status"] = "NO_PSU"
            data["message"] = "No configured power supply session. Continuing without voltage apply."
            self._append_step_result(project_id=project_id, result_id=result_id, status="WARN", data=data)
            log.warning(
                "case voltage apply skipped | run=%s case=%s condition=%s target_voltage_v=%s reason=no_power_supply_session",
                run_id,
                getattr(case, "key", ""),
                condition,
                target_voltage_v,
            )
            return

        try:
            if not hasattr(power_supply, "set_voltage"):
                raise RuntimeError(f"{type(power_supply).__name__} does not support set_voltage()")
            power_supply.set_voltage(float(target_voltage_v))
            if bool((power_control or {}).get("output_on")) and hasattr(power_supply, "output_on"):
                power_supply.output_on()
            settle_time_ms = int(data.get("voltage_settle_time_ms", 0) or 0)
            if settle_time_ms > 0:
                time.sleep(float(settle_time_ms) / 1000.0)
            data["apply_status"] = "APPLIED"
            data["message"] = "Voltage condition applied."
            self._append_step_result(project_id=project_id, result_id=result_id, status="OK", data=data)
            log.info(
                "case voltage applied | run=%s case=%s ruleset_id=%s condition=%s nominal_voltage_v=%s target_voltage_v=%s settle_time_ms=%s power_supply=%s",
                run_id,
                getattr(case, "key", ""),
                data.get("ruleset_id", ""),
                condition,
                data.get("nominal_voltage_v"),
                target_voltage_v,
                data.get("voltage_settle_time_ms", 0),
                type(power_supply).__name__,
            )
        except Exception as exc:
            data["apply_status"] = "ERROR"
            data["message"] = str(exc)
            self._append_step_result(project_id=project_id, result_id=result_id, status="WARN", data=data)
            log.warning(
                "case voltage apply failed | run=%s case=%s condition=%s target_voltage_v=%s error=%s",
                run_id,
                getattr(case, "key", ""),
                condition,
                target_voltage_v,
                exc,
            )

    def _append_step_result(self, *, project_id: str, result_id: str, status: str, data: dict[str, Any]) -> None:
        self.run_repo.append_step_result(
            project_id=project_id,
            result_id=result_id,
            step_name="VOLTAGE_CONDITION",
            status=status,
            data=data,
        )

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except Exception:
            return None


class CaseExecutionPipeline:
    def __init__(self, run_repo: RunRepositorySQLite, metadata_recorder: RunMetadataRecorder):
        self.run_repo = run_repo
        self.metadata_recorder = metadata_recorder
        self.voltage_controller = VoltageConditionController(run_repo)
        self.correction_loader = CorrectionProfileLoader()
        self._last_correction_signature: tuple[Any, ...] | None = None
        self._last_correction_factor_numbers: tuple[int, ...] = ()
        self._last_correction_scpi_status = ""

    def reset_runtime_correction_state(self) -> None:
        self._last_correction_signature = None
        self._last_correction_factor_numbers = ()
        self._last_correction_scpi_status = ""

    def _resolved_correction_factor_numbers(self, resolution: dict[str, Any]) -> tuple[int, ...]:
        out: list[int] = []
        for factor_id in list(resolution.get("resolved_factors") or []):
            number = _normalize_correction_factor_no(factor_id)
            if number is None:
                continue
            if number not in out:
                out.append(number)
        return tuple(out)

    def _apply_correction_cset_scpi_delta(self, inst, resolution: dict[str, Any]) -> dict[str, Any]:
        current_factors = self._resolved_correction_factor_numbers(resolution)
        active = (
            bool(resolution.get("enabled"))
            and str(resolution.get("storage_kind") or "") == "instrument_factor"
            and str(resolution.get("mode") or "").lower() == "instrument"
            and str(resolution.get("reason") or "") == "READY"
        )
        if not active:
            current_factors = ()

        signature = (
            bool(active),
            str(resolution.get("current_path") or ""),
            str(resolution.get("measurement_role") or ""),
            current_factors,
        )
        previous_factors = set(self._last_correction_factor_numbers)
        current_factor_set = set(current_factors)
        off_factors = tuple(sorted(previous_factors - current_factor_set))
        on_factors = tuple(sorted(current_factor_set - previous_factors))
        commands = [
            _correction_cset_command(factor_no, False)
            for factor_no in off_factors
        ] + [
            _correction_cset_command(factor_no, True)
            for factor_no in on_factors
        ]
        skipped_factor_ids = [
            str(factor_id)
            for factor_id in list(resolution.get("resolved_factors") or [])
            if _normalize_correction_factor_no(factor_id) is None
        ]
        trace = {
            "correction_scpi_status": "SKIPPED",
            "correction_scpi_commands": list(commands),
            "correction_scpi_on_factors": list(on_factors),
            "correction_scpi_off_factors": list(off_factors),
            "correction_scpi_active_factors": list(current_factors),
            "correction_scpi_previous_factors": list(self._last_correction_factor_numbers),
            "correction_scpi_skipped_factor_ids": skipped_factor_ids,
            "correction_scpi_signature_changed": signature != self._last_correction_signature,
        }

        if signature == self._last_correction_signature:
            trace["correction_scpi_status"] = (
                "SKIPPED_UNCHANGED_NO_WRITE"
                if self._last_correction_scpi_status == "NO_WRITE_CAPABILITY"
                else "SKIPPED_UNCHANGED"
            )
            return trace

        target = _resolve_scpi_write_target(inst)
        if target is None:
            trace["correction_scpi_status"] = "NO_WRITE_CAPABILITY"
            self._last_correction_signature = signature
            self._last_correction_factor_numbers = current_factors
            self._last_correction_scpi_status = str(trace["correction_scpi_status"])
            log.info(
                "correction SCPI no-op | path=%s measurement_role=%s factors=%s reason=%s",
                resolution.get("current_path", ""),
                resolution.get("measurement_role", ""),
                list(current_factors),
                trace["correction_scpi_status"],
            )
            return trace

        if not commands:
            trace["correction_scpi_status"] = "NO_FACTOR_DELTA"
            self._last_correction_signature = signature
            self._last_correction_factor_numbers = current_factors
            self._last_correction_scpi_status = str(trace["correction_scpi_status"])
            log.info(
                "correction SCPI unchanged factors | path=%s measurement_role=%s factors=%s skipped_factor_ids=%s",
                resolution.get("current_path", ""),
                resolution.get("measurement_role", ""),
                list(current_factors),
                skipped_factor_ids,
            )
            return trace

        try:
            for command in commands:
                log.info(
                    "correction SCPI write | path=%s measurement_role=%s command=%s resolved_factors=%s",
                    resolution.get("current_path", ""),
                    resolution.get("measurement_role", ""),
                    command,
                    list(resolution.get("resolved_factors") or []),
                )
                target.write(command)
        except Exception as exc:
            trace["correction_scpi_status"] = "ERROR"
            trace["correction_scpi_error"] = str(exc)
            log.warning(
                "correction SCPI apply failed | path=%s measurement_role=%s commands=%s err=%s",
                resolution.get("current_path", ""),
                resolution.get("measurement_role", ""),
                commands,
                exc,
                exc_info=True,
            )
            return trace

        trace["correction_scpi_status"] = "APPLIED" if active else "DISABLED"
        self._last_correction_signature = signature
        self._last_correction_factor_numbers = current_factors
        self._last_correction_scpi_status = str(trace["correction_scpi_status"])
        return trace

    def create_runner(self, *, project_id: str) -> StepRunner:
        sink = StepResultSinkSQLite(self.run_repo, project_id)
        return StepRunner(ProcedureRegistry(), sink)

    def _invoke_runtime_correction_api(self, inst, resolution: dict[str, Any]) -> dict[str, Any]:
        trace = {
            "correction_enabled": bool(resolution.get("enabled")),
            "correction_mode": str(resolution.get("mode") or ""),
            "correction_bound_path": str(resolution.get("current_path") or ""),
            "resolved_factors": list(resolution.get("resolved_factors") or []),
            "resolved_set": str(resolution.get("resolved_set") or ""),
            "resolved_sets": list(resolution.get("resolved_sets") or []),
            "measurement_role": str(resolution.get("measurement_role") or ""),
            "apply_model": str(resolution.get("apply_model") or ""),
            "correction_breakdown": {
                "storage_kind": str(resolution.get("storage_kind") or ""),
                "measurement_role": str(resolution.get("measurement_role") or ""),
                "current_path": str(resolution.get("current_path") or ""),
                "resolved_factors": list(resolution.get("resolved_factors") or []),
                "resolved_set": str(resolution.get("resolved_set") or ""),
                "resolved_sets": list(resolution.get("resolved_sets") or []),
            },
            "correction_applied": False,
            "reason": str(resolution.get("reason") or "DISABLED"),
            "instrument_apply_status": "SKIPPED",
        }
        scpi_trace = self._apply_correction_cset_scpi_delta(inst, resolution)
        trace.update(scpi_trace)
        trace["correction_breakdown"].update(
            {
                "correction_scpi_status": scpi_trace.get("correction_scpi_status", ""),
                "correction_scpi_commands": list(scpi_trace.get("correction_scpi_commands") or []),
                "correction_scpi_active_factors": list(scpi_trace.get("correction_scpi_active_factors") or []),
                "correction_scpi_previous_factors": list(scpi_trace.get("correction_scpi_previous_factors") or []),
            }
        )
        if not resolution.get("enabled"):
            if scpi_trace.get("correction_scpi_status") in {"APPLIED", "DISABLED", "NO_FACTOR_DELTA", "NO_WRITE_CAPABILITY"}:
                trace["instrument_apply_status"] = str(scpi_trace.get("correction_scpi_status") or "SKIPPED")
            return trace
        if str(resolution.get("storage_kind") or "") != "instrument_factor":
            trace["instrument_apply_status"] = "LEGACY_RESULT_CORRECTION"
            return trace
        if str(resolution.get("mode") or "").lower() != "instrument":
            trace["instrument_apply_status"] = "MODE_OFF"
            return trace
        if str(resolution.get("reason") or "") not in {"READY", "MODE_OFF"}:
            trace["instrument_apply_status"] = str(scpi_trace.get("correction_scpi_status") or "NO_RESOLVED_FACTORS")
            return trace
        if inst is None:
            trace["instrument_apply_status"] = "NO_INSTRUMENT"
            trace["reason"] = "NO_INSTRUMENT"
            return trace

        enabled = bool(resolution.get("resolved_factors")) or bool(resolution.get("resolved_set"))
        resolved_factors = list(resolution.get("resolved_factors") or [])
        resolved_set = str(resolution.get("resolved_set") or "")
        if scpi_trace.get("correction_scpi_status") in {"APPLIED", "SKIPPED_UNCHANGED", "NO_FACTOR_DELTA"}:
            trace["correction_applied"] = enabled
            trace["instrument_apply_status"] = str(scpi_trace.get("correction_scpi_status") or "APPLIED_SCPI")
            return trace
        try:
            if hasattr(inst, "apply_correction_selection"):
                inst.apply_correction_selection(
                    enabled=enabled,
                    factor_ids=resolved_factors,
                    resolved_set_id=resolved_set,
                    context=dict(resolution),
                )
                trace["correction_applied"] = enabled
                trace["instrument_apply_status"] = "APPLIED_MULTI"
                return trace
            if hasattr(inst, "apply_correction_factors"):
                inst.apply_correction_factors(resolved_factors)
                if hasattr(inst, "set_correction_enabled"):
                    inst.set_correction_enabled(enabled)
                trace["correction_applied"] = enabled
                trace["instrument_apply_status"] = "APPLIED_FACTORS"
                return trace
            if hasattr(inst, "apply_correction_set"):
                inst.apply_correction_set(resolved_set)
                if hasattr(inst, "set_correction_enabled"):
                    inst.set_correction_enabled(enabled)
                trace["correction_applied"] = enabled
                trace["instrument_apply_status"] = "APPLIED_SINGLE_SET"
                return trace
            if hasattr(inst, "set_correction_enabled") and not enabled:
                inst.set_correction_enabled(False)
                trace["instrument_apply_status"] = "DISABLED_ON_INSTRUMENT"
                return trace
        except Exception as exc:
            trace["instrument_apply_status"] = "ERROR"
            trace["reason"] = f"INSTRUMENT_APPLY_ERROR: {exc}"
            trace["error"] = str(exc)
            return trace

        trace["instrument_apply_status"] = "INSTRUMENT_API_UNAVAILABLE"
        trace["reason"] = "INSTRUMENT_API_UNAVAILABLE"
        return trace

    def _apply_runtime_correction_before_measurement(self, *, recipe, case, inst) -> dict[str, Any]:
        recipe_meta = getattr(recipe, "meta", {}) or {}
        resolution = resolve_runtime_correction(recipe_meta, case)
        apply_trace = self._invoke_runtime_correction_api(inst, resolution)
        apply_trace.setdefault("test_type", str(getattr(case, "test_type", "") or ""))
        apply_trace.setdefault("case_key", str(getattr(case, "key", "") or ""))
        return apply_trace

    def iter_cases_for_execution(self, *, ruleset, recipe, overrides, selected_case_keys: Optional[list[str]] = None):
        cases_it = apply_overrides(expand_recipe(ruleset, recipe), overrides)
        if not selected_case_keys:
            for case in cases_it:
                yield case
            return

        ordered_keys = [str(k or "") for k in selected_case_keys if str(k or "")]
        if not ordered_keys:
            return

        selected_set = set(ordered_keys)
        pending: dict[str, object] = {}
        emitted: set[str] = set()
        next_index = 0

        for case in cases_it:
            key = str(getattr(case, "key", "") or "")
            if not key or key not in selected_set or key in emitted:
                continue
            pending[key] = case
            while next_index < len(ordered_keys):
                expected_key = ordered_keys[next_index]
                ready = pending.get(expected_key)
                if ready is None:
                    break
                yield ready
                emitted.add(expected_key)
                pending.pop(expected_key, None)
                next_index += 1
            if next_index >= len(ordered_keys):
                break

        while next_index < len(ordered_keys):
            expected_key = ordered_keys[next_index]
            ready = pending.get(expected_key)
            if ready is None:
                log.warning("selected case key not found during streamed execution | key=%s", expected_key)
                next_index += 1
                continue
            yield ready
            pending.pop(expected_key, None)
            next_index += 1

    def should_prompt_dut_reconfigure(self, *, dut_control_mode: str, previous_case, current_case) -> bool:
        if str(dut_control_mode or "manual").strip().lower() != "manual":
            return False
        if current_case is None:
            return False
        if previous_case is None:
            return True
        return self.dut_reconfigure_key(previous_case) != self.dut_reconfigure_key(current_case)

    def build_dut_prompt_payload(self, previous_case, current_case, dut_control_mode: str) -> dict[str, Any]:
        prev_key = self.dut_reconfigure_key(previous_case) if previous_case is not None else None
        previous_tags = dict(getattr(previous_case, "tags", {}) or {}) if previous_case is not None else {}
        current_tags = dict(getattr(current_case, "tags", {}) or {})
        curr_key = self.dut_reconfigure_key(current_case)
        previous = {
            "band": getattr(previous_case, "band", None) if previous_case is not None else None,
            "center_freq_mhz": getattr(previous_case, "center_freq_mhz", None) if previous_case is not None else None,
            "bw_mhz": getattr(previous_case, "bw_mhz", None) if previous_case is not None else None,
            "standard": getattr(previous_case, "standard", None) if previous_case is not None else None,
            "phy_mode": previous_tags.get("phy_mode"),
            "data_rate": previous_tags.get("data_rate"),
            "voltage_condition": previous_tags.get("voltage_condition"),
            "target_voltage_v": previous_tags.get("target_voltage_v"),
            "nominal_voltage_v": previous_tags.get("nominal_voltage_v"),
        }
        current = {
            "band": getattr(current_case, "band", None),
            "center_freq_mhz": getattr(current_case, "center_freq_mhz", None),
            "bw_mhz": getattr(current_case, "bw_mhz", None),
            "standard": getattr(current_case, "standard", None),
            "phy_mode": current_tags.get("phy_mode"),
            "data_rate": current_tags.get("data_rate"),
            "voltage_condition": current_tags.get("voltage_condition"),
            "target_voltage_v": current_tags.get("target_voltage_v"),
            "nominal_voltage_v": current_tags.get("nominal_voltage_v"),
        }
        instructions = []
        if prev_key is None or previous.get("center_freq_mhz") != current.get("center_freq_mhz"):
            instructions.append(f"Frequency: {current.get('center_freq_mhz')} MHz")
        if prev_key is None or previous.get("bw_mhz") != current.get("bw_mhz"):
            instructions.append(f"Bandwidth: {current.get('bw_mhz')} MHz")
        if prev_key is None or previous.get("band") != current.get("band"):
            instructions.append(f"Band: {current.get('band')}")
        return {
            "dut_control_mode": dut_control_mode,
            "previous_setup_key": prev_key,
            "current_setup_key": curr_key,
            "previous": previous,
            "current": current,
            "instructions": instructions,
            "case_key": getattr(current_case, "key", ""),
            "test_type": getattr(current_case, "test_type", ""),
            "standard": getattr(current_case, "standard", ""),
        }

    def should_confirm_data_rate_change(self, *, dut_control_mode: str, previous_case, current_case) -> bool:
        if str(dut_control_mode or "manual").strip().lower() != "manual":
            return False
        if previous_case is None or current_case is None:
            return False

        current_tags = dict(getattr(current_case, "tags", {}) or {})
        current_data_rate = str(current_tags.get("data_rate", "") or "").strip()
        if not current_data_rate:
            return False

        if not bool(current_tags.get("data_rate_policy_applied")):
            return False

        previous_standard = str(getattr(previous_case, "standard", "") or "").strip()
        current_standard = str(getattr(current_case, "standard", "") or "").strip()
        previous_data_rate = str(dict(getattr(previous_case, "tags", {}) or {}).get("data_rate", "") or "").strip()
        return (previous_standard != current_standard) or (previous_data_rate != current_data_rate)

    def build_data_rate_prompt_payload(self, previous_case, current_case, dut_control_mode: str) -> dict[str, Any]:
        previous_tags = dict(getattr(previous_case, "tags", {}) or {}) if previous_case is not None else {}
        current_tags = dict(getattr(current_case, "tags", {}) or {})
        current_standard = str(getattr(current_case, "standard", "") or "").strip()
        current_data_rate = str(current_tags.get("data_rate", "") or "").strip()
        current_test_type = normalize_test_type_symbol(getattr(current_case, "test_type", ""))
        return {
            "prompt_kind": "data_rate_change",
            "dialog_title": "Change DUT Data Rate",
            "dut_control_mode": dut_control_mode,
            "previous_setup_key": self.data_rate_change_key(previous_case) if previous_case is not None else None,
            "current_setup_key": self.data_rate_change_key(current_case),
            "previous": {
                "standard": str(getattr(previous_case, "standard", "") or "").strip() if previous_case is not None else "",
                "data_rate": str(previous_tags.get("data_rate", "") or "").strip(),
                "band": getattr(previous_case, "band", None) if previous_case is not None else None,
                "center_freq_mhz": getattr(previous_case, "center_freq_mhz", None) if previous_case is not None else None,
                "bw_mhz": getattr(previous_case, "bw_mhz", None) if previous_case is not None else None,
                "phy_mode": previous_tags.get("phy_mode"),
            },
            "current": {
                "standard": current_standard,
                "data_rate": current_data_rate,
                "band": getattr(current_case, "band", None),
                "center_freq_mhz": getattr(current_case, "center_freq_mhz", None),
                "bw_mhz": getattr(current_case, "bw_mhz", None),
                "phy_mode": current_tags.get("phy_mode"),
            },
            "instructions": [],
            "case_key": getattr(current_case, "key", ""),
            "test_type": current_test_type,
            "standard": current_standard,
            "requested_standard": current_standard,
            "requested_data_rate": current_data_rate,
            "data_rate_policy_apply_to": list(current_tags.get("data_rate_policy_apply_to") or []),
            "data_rate_policy_status": str(current_tags.get("data_rate_policy_status", "") or ""),
            "data_rate_policy_applied": bool(current_tags.get("data_rate_policy_applied")),
        }

    def execute_case(
        self,
        *,
        project_id: str,
        preset_id: str,
        run_id: str,
        runner: StepRunner,
        recipe,
        case,
        ruleset,
        inst,
        session=None,
        power_control: dict[str, Any] | None = None,
        equipment_profile_name: str | None = None,
    ) -> tuple[str, str]:
        result_id = self.metadata_recorder.create_result_stub(
            project_id=project_id,
            run_id=run_id,
            case=case,
            ruleset=ruleset,
        )
        self.metadata_recorder.record_case_artifacts(
            project_id=project_id,
            preset_id=preset_id,
            run_id=run_id,
            result_id=result_id,
            recipe=recipe,
            case=case,
            ruleset=ruleset,
        )
        self.voltage_controller.apply_case_voltage(
            project_id=project_id,
            result_id=result_id,
            run_id=run_id,
            case=case,
            session=session,
            power_control=power_control,
            equipment_profile_name=equipment_profile_name,
        )
        correction_apply_trace = self._apply_runtime_correction_before_measurement(
            recipe=recipe,
            case=case,
            inst=inst,
        )
        self.run_repo.append_step_result(
            project_id=project_id,
            result_id=result_id,
            step_name="CORRECTION_APPLY",
            status="OK" if correction_apply_trace.get("correction_applied") else "INFO",
            data=correction_apply_trace,
        )
        values = runner.run_case(run_id, result_id, case, inst)
        correction_meta = dict((getattr(recipe, "meta", {}) or {}).get("correction") or {})
        correction_profile = self.correction_loader.get_profile(str(correction_meta.get("profile_name", "") or ""))
        corrected_values, correction_trace = apply_correction_to_result(
            values=values,
            recipe_meta=getattr(recipe, "meta", {}) or {},
            case=case,
            profile=correction_profile,
        )
        merged_breakdown = dict(correction_trace.get("correction_breakdown") or {})
        merged_breakdown.update(
            {
                "instrument_apply_status": correction_apply_trace.get("instrument_apply_status", ""),
                "resolved_factors": list(correction_apply_trace.get("resolved_factors") or []),
                "resolved_set": str(correction_apply_trace.get("resolved_set") or ""),
                "resolved_sets": list(correction_apply_trace.get("resolved_sets") or []),
                "measurement_role": str(correction_apply_trace.get("measurement_role") or ""),
            }
        )
        correction_trace["correction_breakdown"] = merged_breakdown
        correction_trace.setdefault("resolved_factors", list(correction_apply_trace.get("resolved_factors") or []))
        correction_trace.setdefault("resolved_set", str(correction_apply_trace.get("resolved_set") or ""))
        correction_trace.setdefault("resolved_sets", list(correction_apply_trace.get("resolved_sets") or []))
        correction_trace.setdefault("measurement_role", str(correction_apply_trace.get("measurement_role") or ""))
        correction_trace.setdefault("apply_model", str(correction_apply_trace.get("apply_model") or ""))
        correction_trace.setdefault("instrument_apply_status", str(correction_apply_trace.get("instrument_apply_status") or ""))
        if str((correction_trace.get("correction_breakdown") or {}).get("storage_kind") or "") == "instrument_factor":
            correction_trace["correction_applied"] = bool(correction_apply_trace.get("correction_applied"))
        if str(correction_trace.get("reason") or "") in {"DISABLED", "MODE_OFF"} and correction_apply_trace.get("reason"):
            correction_trace["reason"] = correction_apply_trace.get("reason")
        verdict = self.metadata_recorder.update_final_result(result_id=result_id, values=corrected_values)
        self.run_repo.update_result_correction_fields(result_id=result_id, correction_data=correction_trace)
        return result_id, verdict

    def handle_reconfigure_prompt(
        self,
        *,
        run_id: str,
        dut_control_mode: str,
        previous_case,
        current_case,
        prompt_reconfigure: Optional[Callable[[dict[str, Any]], bool]],
    ) -> bool:
        if not self.should_prompt_dut_reconfigure(
            dut_control_mode=dut_control_mode,
            previous_case=previous_case,
            current_case=current_case,
        ):
            return True

        payload = self.build_dut_prompt_payload(previous_case, current_case, dut_control_mode)
        log.info(
            "dut reconfigure required | run=%s previous=%s current=%s case=%s",
            run_id,
            payload.get("previous_setup_key"),
            payload.get("current_setup_key"),
            payload.get("case_key"),
        )
        accepted = True
        if prompt_reconfigure is not None:
            accepted = bool(prompt_reconfigure(payload))
        if not accepted:
            log.info(
                "dut reconfigure aborted by user | run=%s case=%s current=%s",
                run_id,
                payload.get("case_key"),
                payload.get("current_setup_key"),
            )
            return False
        log.info(
            "dut reconfigure confirmed by user | run=%s case=%s current=%s",
            run_id,
            payload.get("case_key"),
            payload.get("current_setup_key"),
        )
        return True

    def handle_data_rate_change_prompt(
        self,
        *,
        run_id: str,
        dut_control_mode: str,
        previous_case,
        current_case,
        prompt_reconfigure: Optional[Callable[[dict[str, Any]], bool]],
    ) -> bool:
        if not self.should_confirm_data_rate_change(
            dut_control_mode=dut_control_mode,
            previous_case=previous_case,
            current_case=current_case,
        ):
            return True

        payload = self.build_data_rate_prompt_payload(previous_case, current_case, dut_control_mode)
        log.info(
            "data rate change confirmation required | run=%s case=%s previous=%s current=%s standard=%s data_rate=%s test_type=%s apply_to=%s",
            run_id,
            payload.get("case_key"),
            payload.get("previous_setup_key"),
            payload.get("current_setup_key"),
            payload.get("requested_standard"),
            payload.get("requested_data_rate"),
            payload.get("test_type"),
            payload.get("data_rate_policy_apply_to", []),
        )
        accepted = True
        if prompt_reconfigure is not None:
            accepted = bool(prompt_reconfigure(payload))
        if not accepted:
            log.info(
                "data rate change confirmation aborted by user | run=%s case=%s standard=%s data_rate=%s",
                run_id,
                payload.get("case_key"),
                payload.get("requested_standard"),
                payload.get("requested_data_rate"),
            )
            return False
        log.info(
            "data rate change confirmed by user | run=%s case=%s standard=%s data_rate=%s",
            run_id,
            payload.get("case_key"),
            payload.get("requested_standard"),
            payload.get("requested_data_rate"),
        )
        return True

    def case_setup_key(self, case) -> tuple:
        tags = dict(getattr(case, "tags", {}) or {})
        phy_mode = str(tags.get("phy_mode") or getattr(case, "standard", "") or "")
        return (
            str(getattr(case, "band", "") or ""),
            float(getattr(case, "center_freq_mhz", 0.0) or 0.0),
            float(getattr(case, "bw_mhz", 0.0) or 0.0),
            phy_mode,
            str(tags.get("data_rate") or ""),
            str(tags.get("voltage_condition") or ""),
            float(tags.get("target_voltage_v", 0.0) or 0.0),
        )

    def dut_reconfigure_key(self, case) -> tuple:
        return (
            str(getattr(case, "band", "") or ""),
            float(getattr(case, "center_freq_mhz", 0.0) or 0.0),
            float(getattr(case, "bw_mhz", 0.0) or 0.0),
        )

    def data_rate_change_key(self, case) -> tuple:
        if case is None:
            return ("", "")
        tags = dict(getattr(case, "tags", {}) or {})
        return (
            str(getattr(case, "standard", "") or "").strip(),
            str(tags.get("data_rate", "") or "").strip(),
        )
