from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from application.execution_builder import ExecutionBuilder
from application.executor_factory import ExecutorFactory
from application.instrument_manager import InstrumentManager
from application.instrument_profile_resolver import InstrumentProfileResolver
from application.procedures import ProcedureRegistry
from application.runner_step import StepRunner
from application.step_sink_sqlite import StepResultSinkSQLite
from domain.execution import RunContext
from domain.expand import expand_recipe
from domain.overrides import apply_overrides
from infrastructure.run_repo_sqlite import RunRepositorySQLite


log = logging.getLogger(__name__)


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


class CaseExecutionPipeline:
    def __init__(self, run_repo: RunRepositorySQLite, metadata_recorder: RunMetadataRecorder):
        self.run_repo = run_repo
        self.metadata_recorder = metadata_recorder

    def create_runner(self, *, project_id: str) -> StepRunner:
        sink = StepResultSinkSQLite(self.run_repo, project_id)
        return StepRunner(ProcedureRegistry(), sink)

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
        return self.case_setup_key(previous_case) != self.case_setup_key(current_case)

    def build_dut_prompt_payload(self, previous_case, current_case, dut_control_mode: str) -> dict[str, Any]:
        prev_key = self.case_setup_key(previous_case) if previous_case is not None else None
        curr_key = self.case_setup_key(current_case)
        previous = {
            "band": getattr(previous_case, "band", None) if previous_case is not None else None,
            "center_freq_mhz": getattr(previous_case, "center_freq_mhz", None) if previous_case is not None else None,
            "bw_mhz": getattr(previous_case, "bw_mhz", None) if previous_case is not None else None,
            "phy_mode": (dict(getattr(previous_case, "tags", {}) or {}).get("phy_mode") if previous_case is not None else None),
        }
        current = {
            "band": getattr(current_case, "band", None),
            "center_freq_mhz": getattr(current_case, "center_freq_mhz", None),
            "bw_mhz": getattr(current_case, "bw_mhz", None),
            "phy_mode": dict(getattr(current_case, "tags", {}) or {}).get("phy_mode"),
        }
        instructions = []
        if prev_key is None or previous.get("center_freq_mhz") != current.get("center_freq_mhz"):
            instructions.append(f"Frequency: {current.get('center_freq_mhz')} MHz")
        if prev_key is None or previous.get("bw_mhz") != current.get("bw_mhz"):
            instructions.append(f"Bandwidth: {current.get('bw_mhz')} MHz")
        if prev_key is None or previous.get("phy_mode") != current.get("phy_mode"):
            instructions.append(f"Mode: {current.get('phy_mode') or current_case.standard}")
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
        values = runner.run_case(run_id, result_id, case, inst)
        verdict = self.metadata_recorder.update_final_result(result_id=result_id, values=values)
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

    def case_setup_key(self, case) -> tuple:
        tags = dict(getattr(case, "tags", {}) or {})
        phy_mode = str(tags.get("phy_mode") or getattr(case, "standard", "") or "")
        return (
            str(getattr(case, "band", "") or ""),
            float(getattr(case, "center_freq_mhz", 0.0) or 0.0),
            float(getattr(case, "bw_mhz", 0.0) or 0.0),
            phy_mode,
        )
