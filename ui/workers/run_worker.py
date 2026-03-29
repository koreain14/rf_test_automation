from __future__ import annotations

from threading import Event

from PySide6.QtCore import QThread, Signal


class RunWorker(QThread):
    progress = Signal(int, str, object)   # count, last_status, case_info
    finished = Signal(str, str, str)   # final_status, run_id, error_text
    prompt_required = Signal(object)   # payload dict

    def __init__(self, run_service, project_id, preset_id, run_id, ruleset, recipe, overrides, equipment_profile_name=None, selected_case_keys=None):
        super().__init__()
        self.run_service = run_service
        self.project_id = project_id
        self.preset_id = preset_id
        self.run_id = run_id
        self.ruleset = ruleset
        self.recipe = recipe
        self.overrides = overrides
        self.equipment_profile_name = equipment_profile_name
        self.selected_case_keys = list(selected_case_keys or [])
        self._stop = False
        self._error_text = ""
        self._prompt_event: Event | None = None
        self._prompt_response: bool = False

    def request_stop(self):
        self._stop = True
        if self._prompt_event is not None:
            self._prompt_response = False
            self._prompt_event.set()

    def respond_to_prompt(self, accepted: bool) -> None:
        self._prompt_response = bool(accepted)
        if self._prompt_event is not None:
            self._prompt_event.set()

    def _prompt_reconfigure(self, payload: dict) -> bool:
        event = Event()
        self._prompt_event = event
        self._prompt_response = False
        self.prompt_required.emit(payload)
        event.wait()
        self._prompt_event = None
        return bool(self._prompt_response)

    def run(self):
        import traceback
        self._error_text = ""

        try:
            def should_stop():
                return self._stop

            def on_progress(count, status, case_info=None):
                self.progress.emit(count, status, case_info)

            final_status = self.run_service.run(
                project_id=self.project_id,
                preset_id=self.preset_id,
                run_id=self.run_id,
                ruleset=self.ruleset,
                recipe=self.recipe,
                overrides=self.overrides,
                should_stop=should_stop,
                on_progress=on_progress,
                equipment_profile_name=self.equipment_profile_name,
                selected_case_keys=self.selected_case_keys,
                prompt_reconfigure=self._prompt_reconfigure,
            )

        except Exception:
            self._error_text = traceback.format_exc()
            final_status = "ERROR"

        self.finished.emit(final_status, self.run_id, self._error_text)