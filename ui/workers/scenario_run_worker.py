from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal


class ScenarioRunWorker(QThread):
    progress = Signal(int, int, str, str)   # processed, total, preset_name, last_status
    finished = Signal(str, object, str)     # final_status, summaries(list), error_text

    def __init__(self, run_service, run_repo, plan_snapshots, total_cases: int):
        super().__init__()
        self.run_service = run_service
        self.run_repo = run_repo
        self.plan_snapshots = plan_snapshots
        self.total_cases = total_cases
        self._stop = False
        self._error_text = ""

    def request_stop(self):
        self._stop = True

    def run(self):
        summaries = []
        completed_before_current = 0

        for plan in self.plan_snapshots:
            if self._stop:
                break

            project_id = plan["project_id"]
            preset_id = plan["preset_id"]
            preset_name = plan["preset_name"]
            ruleset = plan["ruleset"]
            recipe = plan["recipe"]
            overrides = plan["overrides"]
            current_case_count = plan.get("case_count", 0)
            equipment_profile_name = plan.get("equipment_profile_name")
            selected_case_keys = plan.get("selected_case_keys") or []

            run_id = self.run_repo.create_run(project_id=project_id, preset_id=preset_id)
            final_status = "ERROR"

            def should_stop():
                return self._stop

            def on_progress(count, status, case_info=None):
                processed_global = completed_before_current + count
                self.progress.emit(processed_global, self.total_cases, preset_name, status)

            try:
                final_status = self.run_service.run(
                    project_id=project_id,
                    preset_id=preset_id,
                    run_id=run_id,
                    ruleset=ruleset,
                    recipe=recipe,
                    overrides=overrides,
                    should_stop=should_stop,
                    on_progress=on_progress,
                    equipment_profile_name=equipment_profile_name,
                    selected_case_keys=selected_case_keys,
                )
            except Exception:
                self._error_text = traceback.format_exc()
                final_status = "ERROR"
            finally:
                try:
                    self.run_repo.finish_run(run_id=run_id, status=final_status)
                except Exception:
                    if not self._error_text:
                        self._error_text = traceback.format_exc()

            try:
                counts = self.run_repo.get_run_status_counts(project_id=project_id, run_id=run_id)
            except Exception:
                counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "ERROR": 0}

            summaries.append({
                "plan_id": plan["plan_id"],
                "preset_id": preset_id,
                "preset_name": preset_name,
                "run_id": run_id,
                "final_status": final_status,
                "case_count": current_case_count,
                "counts": counts,
            })

            completed_before_current += current_case_count

            if final_status == "ERROR":
                self.finished.emit("ERROR", summaries, self._error_text)
                return

        final = "STOPPED" if self._stop else "DONE"
        self.finished.emit(final, summaries, self._error_text)
