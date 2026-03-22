# application/run_service_step.py
from __future__ import annotations
import logging
from typing import Callable, Optional

log = logging.getLogger(__name__)

from application.procedures import ProcedureRegistry
from application.runner_step import StepRunner
from application.step_sink_sqlite import StepResultSinkSQLite
from application.instrument_manager import InstrumentManager
from infrastructure.run_repo_sqlite import RunRepositorySQLite
from domain.overrides import apply_overrides
from domain.expand import expand_recipe
from application.execution_builder import ExecutionBuilder
from application.executor_factory import ExecutorFactory
from application.instrument_profile_resolver import InstrumentProfileResolver
from application.path_resolver import PathResolver
from domain.execution import RunContext


class RunServiceStep:
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

    def _cleanup_session(self, session, power_control: dict | None = None) -> None:
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

    def __init__(self, run_repo: RunRepositorySQLite, instrument_manager: InstrumentManager):
        self.run_repo = run_repo
        self.instrument_manager = instrument_manager
        self.execution_builder = ExecutionBuilder()
        self.instrument_profile_resolver = InstrumentProfileResolver()
        self.path_resolver = PathResolver()

    def _build_execution_case_payload(self, case, ruleset) -> dict:
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
            "instrument": dict(case.instrument or {}),
            "tags": dict(case.tags or {}),
        }

    def _append_bridge_step_result(
        self,
        project_id: str,
        result_id: str,
        step_name: str,
        status: str,
        data: dict,
    ) -> None:
        """Compatibility helper for bridge metadata records.

        RunRepositorySQLite.append_step_result requires project_id as the first
        argument. Earlier bridge code called it positionally without project_id,
        which raised a TypeError at runtime. Keep the repository API unchanged
        and route all bridge writes through this helper to prevent regressions.
        """
        self.run_repo.append_step_result(
            project_id=project_id,
            result_id=result_id,
            step_name=step_name,
            status=status,
            data=data,
        )

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
        self._append_bridge_step_result(project_id, result_id, "EXECUTION_MODEL", "OK", data)

    def _record_run_context(self, result_id: str, recipe, project_id: str) -> None:
        data = dict((recipe.meta or {})) if recipe else {}
        data.setdefault("_display", {})["execution_policy"] = (data.get("execution_policy") or {})
        data.setdefault("_display", {})["ordering_policy"] = (data.get("ordering_policy") or {})
        self._append_bridge_step_result(project_id, result_id, "RUN_CONTEXT", "INFO", data)

    def _iter_cases_for_execution(self, *, ruleset, recipe, overrides, selected_case_keys: Optional[list[str]] = None):
        """
        Yield execution cases without materializing the full expanded case list.

        - When selected_case_keys is provided, preserve that exact key order.
        - Stream expanded cases once and keep only pending selected cases.
        - Fall back to raw expanded order only when no selection/query key list is supplied.
        """
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
                resolved = self.instrument_profile_resolver.resolve(step.instrument_profile_name)
                step.metadata["resolved_profile"] = resolved
                item["profile"] = resolved
            except Exception as exc:
                item.update({
                    "status": "PROFILE_ERROR",
                    "message": str(exc),
                })
                preview_items.append(item)
                continue

            try:
                executor = ExecutorFactory.get_executor(step)
            except Exception as exc:
                item.update({
                    "status": "NO_PREVIEW",
                    "message": str(exc),
                })
                preview_items.append(item)
                continue

            try:
                result = executor.execute(step, ctx)
                item.update({
                    "status": result.status,
                    "message": result.message,
                })
            except Exception as exc:
                item.update({
                    "status": "ERROR",
                    "message": str(exc),
                })
            preview_items.append(item)

        self._append_bridge_step_result(
            project_id,
            result_id,
            "EXECUTOR_PREVIEW",
            "OK",
            {
                "case_key": case.key,
                "standard": case.standard,
                "test_type": case.test_type,
                "step_count": len(steps),
                "items": preview_items,
            },
        )

    def run(
        self,
        project_id: str,
        preset_id: str,
        run_id: str,
        ruleset,
        recipe,
        overrides,
        should_stop: Callable[[], bool],
        on_progress: Optional[Callable[[int, str, dict | None], None]] = None,
        equipment_profile_name: Optional[str] = None,
        selected_case_keys: Optional[list[str]] = None,
    ) -> str:
        session = None
        inst = None
        power_control = (((recipe.meta or {}).get("power_control") or {}) if recipe else {})
        try:
            log.info(
                "run start | project=%s preset=%s run=%s equipment_profile=%s",
                project_id, preset_id, run_id, equipment_profile_name or "(none)"
            )

            ordered_case_keys = [str(k or "") for k in (selected_case_keys or []) if str(k or "")]
            if ordered_case_keys:
                log.info(
                    "selected/filter runnable set applied | run=%s selected_count=%s",
                    run_id,
                    len(ordered_case_keys),
                )
            else:
                log.info(
                    "selected/filter runnable set applied | run=%s selected_count=ALL(streamed)",
                    run_id,
                )

            cases = self._iter_cases_for_execution(
                ruleset=ruleset,
                recipe=recipe,
                overrides=overrides,
                selected_case_keys=ordered_case_keys or None,
            )

            # 3) Runner/Instrument/Sink 준비
            rf_path = (((recipe.meta or {}).get("rf_path") or {}) if recipe else {})
            switch_path = (rf_path.get("switch_path") if rf_path else None)
            antenna = (rf_path.get("antenna") if rf_path else None)
            motion_control = (((recipe.meta or {}).get("motion_control") or {}) if recipe else {})

            if equipment_profile_name:
                session = self.instrument_manager.create_session(equipment_profile_name)
                log.info(
                    "session created | equipment_profile=%s devices=%s",
                    equipment_profile_name,
                    self._device_summary(session),
                )

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
                        except Exception as e:
                            log.warning("turntable move skipped/failed | angle=%s error=%s", angle, e)
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
                        except Exception as e:
                            log.warning("mast move skipped/failed | height=%s error=%s", height, e)
                    else:
                        log.info("mast move skipped | no configured/connected mast")

            inst = None
            if session is not None:
                inst = getattr(session, "analyzer", None)

            if inst is None:
                inst = self.instrument_manager.get_measurement_instrument()
                log.info("session analyzer missing -> fallback instrument=%s", type(inst).__name__)
                run_meta = self.instrument_manager.build_session_metadata(
                    equipment_profile_name=equipment_profile_name,
                    session=session,
                    fallback_instrument=inst,
                )
            else:
                log.info("session analyzer selected -> instrument=%s", type(inst).__name__)
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
            try:
                self.run_repo.update_run_metadata(run_id=run_id, metadata=run_meta)
                log.info("run metadata saved | run=%s meta=%s", run_id, run_meta)
            except Exception:
                log.warning("run metadata save skipped", exc_info=True)

            sink = StepResultSinkSQLite(self.run_repo, project_id)
            runner = StepRunner(ProcedureRegistry(), sink)

            count = 0
            for case in cases:
                if should_stop():
                    log.info("run aborted | run=%s", run_id)
                    return "ABORTED"

                # 4) result stub 생성
                result_id = self.run_repo.create_result_stub(
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
                    }
                )

                # 5) execution-model bridge metadata (non-fatal, but never conditionally skipped)
                try:
                    self._record_execution_step_model(result_id, case, ruleset, run_id, project_id)
                except Exception:
                    log.warning("execution-model record failed for case=%s", case.key, exc_info=True)
                try:
                    self._record_executor_preview(result_id, case, ruleset, run_id, project_id, preset_id)
                except Exception:
                    log.warning("executor-preview record failed for case=%s", case.key, exc_info=True)

                # 6) steps 실행 → ctx.values 리턴
                values = runner.run_case(result_id, case, inst)

                verdict = values.get("verdict", "ERROR")
                self.run_repo.update_result_final(
                    result_id=result_id,
                    status=verdict if verdict in ("PASS", "FAIL", "SKIP", "ERROR") else "ERROR",
                    margin_db=values.get("margin_db"),
                    measured_value=values.get("measured_value"),
                    limit_value=values.get("limit_value"),
                )

                count += 1
                if on_progress:
                    on_progress(count, verdict, {"channel": case.channel, "test_type": case.test_type, "standard": case.standard, "case_key": case.key})

            return "DONE"
        except Exception:
            # ✅ Do NOT swallow errors. Log full traceback and re-raise so UI can show it.
            log.exception("Run failed")
            raise

        finally:
            self._cleanup_session(session, power_control)
