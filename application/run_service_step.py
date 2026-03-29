from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Callable, Optional

from application.execution_builder import ExecutionBuilder
from application.instrument_manager import InstrumentManager
from application.instrument_profile_resolver import InstrumentProfileResolver
from application.path_resolver import PathResolver
from application.run_execution_support import (
    CaseExecutionPipeline,
    RunMetadataRecorder,
    RunSessionCoordinator,
)
from infrastructure.run_repo_sqlite import RunRepositorySQLite


log = logging.getLogger(__name__)


class RunServiceStep:
    def __init__(self, run_repo: RunRepositorySQLite, instrument_manager: InstrumentManager):
        self.run_repo = run_repo
        self.instrument_manager = instrument_manager
        self.execution_builder = ExecutionBuilder()
        self.instrument_profile_resolver = InstrumentProfileResolver()
        self.path_resolver = PathResolver()
        self.session_coordinator = RunSessionCoordinator(instrument_manager)
        self.metadata_recorder = RunMetadataRecorder(
            run_repo=run_repo,
            execution_builder=self.execution_builder,
            instrument_profile_resolver=self.instrument_profile_resolver,
        )
        self.case_pipeline = CaseExecutionPipeline(
            run_repo=run_repo,
            metadata_recorder=self.metadata_recorder,
        )
        self._active_environment = None
        self._active_environment_lock = RLock()

    def get_active_instrument(self):
        with self._active_environment_lock:
            env = self._active_environment
            return getattr(env, "instrument", None) if env is not None else None

    # Compatibility wrappers retained so partial migrations do not break local callers.
    def _device_summary(self, session) -> dict:
        return self.session_coordinator._device_summary(session)

    def _require_capability(self, device, attr_name: str, capability: str, equipment_profile_name: str | None) -> None:
        self.session_coordinator._require_capability(device, attr_name, capability, equipment_profile_name)

    def _cleanup_session(self, session, power_control: dict | None = None) -> None:
        self.session_coordinator.cleanup(session, power_control)

    def _build_execution_case_payload(self, case, ruleset) -> dict:
        return self.metadata_recorder._build_execution_case_payload(case, ruleset)

    def _append_bridge_step_result(
        self,
        project_id: str,
        result_id: str,
        step_name: str,
        status: str,
        data: dict,
    ) -> None:
        self.metadata_recorder._append_bridge_step_result(
            project_id=project_id,
            result_id=result_id,
            step_name=step_name,
            status=status,
            data=data,
        )

    def _build_execution_steps(self, case, ruleset, run_id: str):
        return self.metadata_recorder._build_execution_steps(case, ruleset, run_id)

    def _record_execution_step_model(self, result_id: str, case, ruleset, run_id: str, project_id: str) -> None:
        self.metadata_recorder._record_execution_step_model(result_id, case, ruleset, run_id, project_id)

    def _record_run_context(self, result_id: str, recipe, project_id: str) -> None:
        self.metadata_recorder._record_run_context(result_id, recipe, project_id)

    def _iter_cases_for_execution(self, *, ruleset, recipe, overrides, selected_case_keys: Optional[list[str]] = None):
        return self.case_pipeline.iter_cases_for_execution(
            ruleset=ruleset,
            recipe=recipe,
            overrides=overrides,
            selected_case_keys=selected_case_keys,
        )

    def _record_executor_preview(self, result_id: str, case, ruleset, run_id: str, project_id: str, preset_id: str) -> None:
        self.metadata_recorder._record_executor_preview(result_id, case, ruleset, run_id, project_id, preset_id)

    def _get_dut_control_mode(self, recipe) -> str:
        return self.session_coordinator.get_dut_control_mode(recipe)

    def _case_setup_key(self, case) -> tuple:
        return self.case_pipeline.case_setup_key(case)

    def _build_dut_prompt_payload(self, previous_case, current_case, dut_control_mode: str) -> dict[str, Any]:
        return self.case_pipeline.build_dut_prompt_payload(previous_case, current_case, dut_control_mode)

    def _should_prompt_dut_reconfigure(self, *, dut_control_mode: str, previous_case, current_case) -> bool:
        return self.case_pipeline.should_prompt_dut_reconfigure(
            dut_control_mode=dut_control_mode,
            previous_case=previous_case,
            current_case=current_case,
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
        prompt_reconfigure: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> str:
        environment = None
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

            cases = self.case_pipeline.iter_cases_for_execution(
                ruleset=ruleset,
                recipe=recipe,
                overrides=overrides,
                selected_case_keys=ordered_case_keys or None,
            )

            environment = self.session_coordinator.prepare_environment(
                equipment_profile_name=equipment_profile_name,
                recipe=recipe,
            )
            with self._active_environment_lock:
                self._active_environment = environment
            self.metadata_recorder.update_run_metadata(run_id=run_id, metadata=environment.run_metadata)

            runner = self.case_pipeline.create_runner(project_id=project_id)

            count = 0
            previous_case = None
            for case in cases:
                if should_stop():
                    log.info("run aborted | run=%s", run_id)
                    return "ABORTED"

                accepted = self.case_pipeline.handle_reconfigure_prompt(
                    run_id=run_id,
                    dut_control_mode=environment.dut_control_mode,
                    previous_case=previous_case,
                    current_case=case,
                    prompt_reconfigure=prompt_reconfigure,
                )
                if not accepted:
                    return "ABORTED"

                _, verdict = self.case_pipeline.execute_case(
                    project_id=project_id,
                    preset_id=preset_id,
                    run_id=run_id,
                    runner=runner,
                    recipe=recipe,
                    case=case,
                    ruleset=ruleset,
                    inst=environment.instrument,
                )

                count += 1
                if on_progress:
                    on_progress(count, verdict, {"channel": case.channel, "test_type": case.test_type, "standard": case.standard, "case_key": case.key})
                previous_case = case

            return "DONE"
        except Exception:
            log.exception("Run failed")
            raise
        finally:
            with self._active_environment_lock:
                self._active_environment = None
            self.session_coordinator.cleanup(
                getattr(environment, "session", None),
                getattr(environment, "power_control", None),
            )
