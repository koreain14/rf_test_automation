from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


class MainWindowRunFacade:
    """Run/results-related compatibility facade for MainWindow."""

    def __init__(self, window):
        self.window = window

    def on_run_progress(self, count: int, last_status: str, case_info=None) -> None:
        self.window._run_controller.handle_run_progress(count, last_status, case_info)

    def on_scenario_run_progress(self, processed: int, total: int, preset_name: str, last_status: str) -> None:
        self.window._run_controller.handle_scenario_run_progress(processed, total, preset_name, last_status)

    def on_start_run(self) -> None:
        self.window._run_controller.start_run()

    def on_start_scenario_run(self) -> None:
        self.window._run_controller.start_scenario_run()

    def on_refresh_runs(self) -> None:
        if hasattr(self.window, "results_widget"):
            self.window.results_widget.refresh_runs()

    def on_load_results(self) -> None:
        if hasattr(self.window, "results_widget"):
            self.window.results_widget.load_results()

    def on_export_results_csv(self) -> None:
        if hasattr(self.window, "results_widget"):
            self.window.results_widget.export_results_csv()

    def on_export_results_excel(self) -> None:
        if hasattr(self.window, "results_widget"):
            self.window.results_widget.export_results_excel()

    def update_result_quick_buttons_style(self) -> None:
        if hasattr(self.window, "results_widget") and hasattr(self.window.results_widget, "_update_result_quick_buttons_style"):
            self.window.results_widget._update_result_quick_buttons_style()

    def on_run_finished(self, final_status: str, run_id: str, error_text: str) -> None:
        self.window._run_controller.handle_run_finished(final_status, run_id, error_text)

    def on_scenario_run_finished(self, final_status: str, summaries: list, error_text: str) -> None:
        self.window._run_controller.handle_scenario_run_finished(final_status, summaries, error_text)

    def on_stop_run(self) -> None:
        self.window._run_controller.stop_run()

    def on_create_rerun(self) -> None:
        w = self.window
        if not w._last_run_id:
            QMessageBox.information(w, "No run", "Run first to generate FAIL-based re-run.")
            return
        if not w._current_plan_node_id:
            return
        ctx = w._plans[w._current_plan_node_id]

        try:
            new_preset_id = w.svc.create_rerun_preset_from_fail(
                project_id=ctx.project_id,
                base_preset_id=ctx.preset_id,
                run_id=w._last_run_id,
            )
            QMessageBox.information(w, "Re-run preset created", f"New preset created.\nPreset ID: {new_preset_id}")
            w._reload_presets(ctx.project_id, select_preset_id=new_preset_id)
        except Exception as e:
            QMessageBox.warning(w, "Re-run failed", str(e))
