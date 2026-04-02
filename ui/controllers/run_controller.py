from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from application.run_display_formatter import build_progress_text, build_status_text
from ui.workers.run_worker import RunWorker
from ui.workers.scenario_run_worker import ScenarioRunWorker


class RunController:
    """Owns runtime orchestration for single-plan and scenario execution."""

    def __init__(self, window):
        self.window = window

    def _resolve_execution_target_keys(self, *, execution_scope: str) -> list[str]:
        """Resolve execution target keys without re-implementing query logic here."""
        scope = str(execution_scope or "all").strip().lower()
        if hasattr(self.window, "_plan_controller") and self.window._plan_controller is not None:
            return list(self.window._plan_controller.execution_target_keys(scope=scope))
        return []

    def _empty_target_message(self, *, execution_scope: str) -> str:
        scope = str(execution_scope or "all").strip().lower()
        if scope == "selected":
            return "선택된 케이스가 없습니다."
        if scope == "filtered":
            return "현재 필터된 케이스가 없습니다."
        return "실행 가능한 케이스가 없습니다."

    def start_run(self) -> None:
        self._start_run_impl(execution_scope="all")

    def start_run_filtered(self) -> None:
        self._start_run_impl(execution_scope="filtered")

    def start_run_selected(self) -> None:
        self._start_run_impl(execution_scope="selected")

    def _start_run_impl(self, execution_scope: str = "all") -> None:
        w = self.window
        if not w._current_plan_node_id:
            QMessageBox.information(w, "No plan", "Add a plan and select it in the tree first.")
            return
        if w._worker and w._worker.isRunning():
            QMessageBox.information(w, "Running", "A run is already in progress.")
            return

        equipment_profile_name = w._current_equipment_profile_name()

        ctx = w._plans.get(w._current_plan_node_id)
        if ctx is None:
            w._current_plan_node_id = None
            QMessageBox.warning(w, "Plan state", "Selected plan is no longer available. Re-add or reselect a plan.")
            return
        selected_case_keys = self._resolve_execution_target_keys(execution_scope=execution_scope)
        if not selected_case_keys:
            QMessageBox.information(w, "No runnable cases", self._empty_target_message(execution_scope=execution_scope))
            return

        preflight = w.preflight_service.validate_plan_context(
            plan_ctx=ctx,
            equipment_profile_name=equipment_profile_name,
        )
        if not preflight.ok:
            QMessageBox.warning(w, "Run Preflight", preflight.summary())
            return

        w._running_preset_name = ctx.preset.name
        w._run_pass_count = 0
        w._run_fail_count = 0
        w._run_skip_count = 0
        w._run_error_count = 0

        total_cases = len(selected_case_keys)
        w._run_total_cases = total_cases
        w._run_processed_cases = 0

        if total_cases > 0:
            w.progress_run.setMaximum(total_cases)
            w.progress_run.setValue(0)
            w.progress_run.setFormat(f"0 / {total_cases}")
        else:
            w.progress_run.setMaximum(100)
            w.progress_run.setValue(0)
            w.progress_run.setFormat("0")

        run_id = w.run_repo.create_run(project_id=ctx.project_id, preset_id=ctx.preset_id)
        w._last_run_id = run_id
        w._running_equipment_profile_name = equipment_profile_name or ""
        w.lbl_status.setText(build_status_text(run_id, ctx.recipe.meta or {}, state="RUNNING"))

        w._worker = RunWorker(
            run_service=w.run_service,
            project_id=ctx.project_id,
            preset_id=ctx.preset_id,
            run_id=run_id,
            ruleset=ctx.ruleset,
            recipe=ctx.recipe,
            overrides=ctx.overrides,
            equipment_profile_name=equipment_profile_name,
            selected_case_keys=selected_case_keys,
        )
        w._worker.progress.connect(w._on_run_progress)
        w._worker.finished.connect(w._on_run_finished)
        if hasattr(w, "_on_run_prompt_required"):
            w._worker.prompt_required.connect(w._on_run_prompt_required)
        w._worker.start()

    def start_scenario_run(self) -> None:
        w = self.window
        if w._worker and w._worker.isRunning():
            QMessageBox.information(w, "Running", "A single-plan run is already in progress.")
            return
        if w._scenario_worker and w._scenario_worker.isRunning():
            QMessageBox.information(w, "Running", "A scenario run is already in progress.")
            return

        equipment_profile_name = w._current_equipment_profile_name()

        plan_ids = w._scenario_controller.scenario_plan_ids_in_tree_order()
        if not plan_ids:
            QMessageBox.information(w, "No plans", "Add plans to the scenario first.")
            return

        plan_contexts = []
        for plan_id in plan_ids:
            ctx = w._plans.get(plan_id)
            if ctx is not None:
                plan_contexts.append(ctx)

        preflight = w.preflight_service.validate_scenario(
            plan_contexts=plan_contexts,
            equipment_profile_name=equipment_profile_name,
        )
        if not preflight.ok:
            QMessageBox.warning(w, "Scenario Preflight", preflight.summary())
            return

        plan_snapshots = []
        total_cases = 0

        for plan_id in plan_ids:
            ctx = w._plans.get(plan_id)
            if not ctx:
                continue

            selected_case_keys = []
            try:
                if hasattr(w._plan_controller, "execution_target_keys_for_plan"):
                    selected_case_keys = list(
                        w._plan_controller.execution_target_keys_for_plan(
                            plan_id=plan_id,
                            scope="all",
                        )
                    )
                cnt = len(selected_case_keys)
            except Exception:
                cnt = 0
                selected_case_keys = []

            total_cases += cnt

            plan_snapshots.append({
                "plan_id": plan_id,
                "project_id": ctx.project_id,
                "preset_id": ctx.preset_id,
                "preset_name": ctx.preset.name,
                "ruleset": ctx.ruleset,
                "recipe": ctx.recipe,
                "overrides": ctx.overrides,
                "case_count": cnt,
                "equipment_profile_name": equipment_profile_name,
                "selected_case_keys": selected_case_keys,
            })

        if not plan_snapshots:
            QMessageBox.information(w, "No plans", "No valid plans found in the scenario.")
            return

        w._scenario_total_cases = total_cases
        w._scenario_processed_cases = 0
        w._scenario_run_summaries = []

        w.progress_run.setMaximum(total_cases if total_cases > 0 else 100)
        w.progress_run.setValue(0)
        w.progress_run.setFormat(f"0 / {total_cases}" if total_cases > 0 else "0")

        w.lbl_status.setText(f"SCENARIO RUN | 0/{total_cases}")

        w._scenario_worker = ScenarioRunWorker(
            run_service=w.run_service,
            run_repo=w.run_repo,
            plan_snapshots=plan_snapshots,
            total_cases=total_cases,
        )
        w._scenario_worker.progress.connect(w._on_scenario_run_progress)
        w._scenario_worker.finished.connect(w._on_scenario_run_finished)
        if hasattr(w, "_on_run_prompt_required"):
            w._scenario_worker.prompt_required.connect(w._on_run_prompt_required)
        w._scenario_worker.start()

    def stop_run(self) -> None:
        w = self.window
        stopped = False

        if w._worker and w._worker.isRunning():
            w._worker.request_stop()
            run_short = w._last_run_id[:8] if w._last_run_id else "--------"
            w.lbl_status.setText(
                f"STOPPING {run_short} | "
                f"P:{w._run_pass_count} F:{w._run_fail_count} "
                f"S:{w._run_skip_count} E:{w._run_error_count}"
            )
            stopped = True

        if w._scenario_worker and w._scenario_worker.isRunning():
            w._scenario_worker.request_stop()
            w.lbl_status.setText(
                f"SCENARIO STOPPING | "
                f"{w._scenario_processed_cases}/{w._scenario_total_cases}"
            )
            stopped = True

        if stopped:
            w.progress_run.setFormat("Stopping...")

    def handle_run_progress(self, count: int, last_status: str, case_info: dict | None = None) -> None:
        w = self.window
        w._run_processed_cases = count
        st = (last_status or "").upper()
        if st == "PASS":
            w._run_pass_count += 1
        elif st == "FAIL":
            w._run_fail_count += 1
        elif st == "SKIP":
            w._run_skip_count += 1
        elif st == "ERROR":
            w._run_error_count += 1

        total = w._run_total_cases if w._run_total_cases > 0 else 0
        current_case = case_info or {}
        meta = w._current_plan_meta() if hasattr(w, "_current_plan_meta") else {}
        if total > 0:
            w.progress_run.setMaximum(total)
            w.progress_run.setValue(min(count, total))
        else:
            w.progress_run.setMaximum(100)
            w.progress_run.setValue(0)
        w.progress_run.setFormat(build_progress_text(count, total, current_case, meta))

        counts_text = f"P:{w._run_pass_count} F:{w._run_fail_count} S:{w._run_skip_count} E:{w._run_error_count}"
        progress_text = f"{count}/{total}" if total > 0 else str(count)
        display_last_status = st if st in ("PASS", "FAIL", "SKIP", "ERROR") else ""
        w.lbl_status.setText(
            build_status_text(
                w._last_run_id or "",
                meta,
                state="RUNNING",
                progress=progress_text,
                counts=counts_text,
                last_status=display_last_status,
                case=current_case,
            )
        )

    def handle_scenario_run_progress(self, processed: int, total: int, preset_name: str, last_status: str) -> None:
        w = self.window
        w._scenario_processed_cases = processed

        if total > 0:
            w.progress_run.setMaximum(total)
            w.progress_run.setValue(min(processed, total))
            w.progress_run.setFormat(f"{processed} / {total}")
        else:
            w.progress_run.setMaximum(100)
            w.progress_run.setValue(0)
            w.progress_run.setFormat(str(processed))

        w.lbl_status.setText(
            f"SCENARIO RUN | {processed}/{total} | {preset_name} | last={last_status}"
        )

    def handle_run_finished(self, final_status: str, run_id: str, error_text: str) -> None:
        w = self.window
        w.run_repo.finish_run(run_id=run_id, status=final_status)

        if w._run_total_cases > 0:
            w.progress_run.setMaximum(w._run_total_cases)
            w.progress_run.setValue(w._run_total_cases)
            w.progress_run.setFormat(f"{w._run_total_cases} / {w._run_total_cases}")
        else:
            w.progress_run.setMaximum(100)
            w.progress_run.setValue(100)
            w.progress_run.setFormat("Done")

        preset_name = w._running_preset_name or "Unknown"

        try:
            counts = w.run_repo.get_run_status_counts(
                project_id=w.project_id,
                run_id=run_id,
            )
        except Exception:
            counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "ERROR": 0}

        pass_cnt = counts.get("PASS", 0)
        fail_cnt = counts.get("FAIL", 0)
        skip_cnt = counts.get("SKIP", 0)
        error_cnt = counts.get("ERROR", 0)

        if final_status == "ERROR":
            meta = w._current_plan_meta() if hasattr(w, "_current_plan_meta") else {}
            w.lbl_status.setText(build_status_text(run_id, meta, state="ERROR"))
            msg = (
                f"Run finished\n\n"
                f"Preset : {preset_name}\n"
                f"Status : {final_status}\n"
                f"PASS   : {pass_cnt}\n"
                f"FAIL   : {fail_cnt}\n"
                f"SKIP   : {skip_cnt}\n"
                f"ERROR  : {error_cnt}\n\n"
                f"{error_text or 'Unknown error'}"
            )
            QMessageBox.critical(w, "Run ERROR", msg)
            return

        counts_text = f"P:{pass_cnt} F:{fail_cnt} S:{skip_cnt} E:{error_cnt}"
        meta = w._current_plan_meta() if hasattr(w, "_current_plan_meta") else {}
        w.lbl_status.setText(
            build_status_text(
                run_id,
                meta,
                state=final_status,
                counts=counts_text,
            )
        )

        msg = (
            f"Run completed\n\n"
            f"Preset : {preset_name}\n"
            f"Status : {final_status}\n"
            f"PASS   : {pass_cnt}\n"
            f"FAIL   : {fail_cnt}\n"
            f"SKIP   : {skip_cnt}\n"
            f"ERROR  : {error_cnt}"
        )

        QMessageBox.information(w, "Run finished", msg)
        w.on_refresh_runs()

    def handle_scenario_run_finished(self, final_status: str, summaries: list, error_text: str) -> None:
        w = self.window
        w._scenario_run_summaries = summaries or []

        total = w._scenario_total_cases
        if total > 0:
            w.progress_run.setMaximum(total)
            w.progress_run.setValue(total)
            w.progress_run.setFormat(f"{total} / {total}")
        else:
            w.progress_run.setMaximum(100)
            w.progress_run.setValue(100)
            w.progress_run.setFormat("Done")

        lines = [f"Scenario completed{w._equipment_display_suffix()}", ""]
        total_pass = total_fail = total_skip = total_error = 0

        for s in w._scenario_run_summaries:
            preset_name = s.get("preset_name", "Unknown")
            run_status = s.get("final_status", "")
            counts = s.get("counts", {}) or {}

            p = counts.get("PASS", 0)
            f = counts.get("FAIL", 0)
            sk = counts.get("SKIP", 0)
            e = counts.get("ERROR", 0)

            total_pass += p
            total_fail += f
            total_skip += sk
            total_error += e

            lines.append(f"{preset_name} | {run_status} | P:{p} F:{f} S:{sk} E:{e}")

        lines.append("")
        lines.append(f"TOTAL | P:{total_pass} F:{total_fail} S:{total_skip} E:{total_error}")

        if final_status == "ERROR":
            w.lbl_status.setText(
                f"SCENARIO ERROR | P:{total_pass} F:{total_fail} S:{total_skip} E:{total_error}"
            )
            if error_text:
                lines.append("")
                lines.append(error_text)
            QMessageBox.critical(w, "Scenario Run ERROR", "\n".join(lines))
        else:
            w.lbl_status.setText(
                f"SCENARIO DONE | P:{total_pass} F:{total_fail} S:{total_skip} E:{total_error}"
            )
            QMessageBox.information(w, "Scenario Run finished", "\n".join(lines))

        w.on_refresh_runs()
