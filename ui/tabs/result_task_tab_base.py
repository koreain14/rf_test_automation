from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtWidgets import QMessageBox

from ui.workers.results_task_worker import ResultsTaskWorker


log = logging.getLogger(__name__)


class ResultTaskTabBase:
    """Shared worker lifecycle helper for results-like tabs.

    This mixin intentionally keeps the existing per-tab public API intact.
    Tabs remain responsible for implementing `_set_busy_impl` so widget-level
    enable/disable behavior can stay local to each tab.
    """

    _task_worker: ResultsTaskWorker | None
    _task_generation: int
    _busy_action: str

    def _init_result_task_support(self) -> None:
        self._task_worker = None
        self._task_generation = 0
        self._busy_action = ""

    def _set_busy_impl(self, busy: bool, action: str = "") -> None:
        raise NotImplementedError

    def _set_busy(self, busy: bool, action: str = "") -> None:
        self._busy_action = action if busy else ""
        self._set_busy_impl(busy, action=action)

    def _finish_worker(self, worker: ResultsTaskWorker) -> None:
        if self._task_worker is worker:
            self._task_worker = None
        worker.deleteLater()
        self._set_busy(False)

    def _cancel_pending_tasks(self) -> None:
        self._task_generation += 1
        self._task_worker = None
        self._busy_action = ""

    def _start_task(
        self,
        *,
        action: str,
        task: Callable[[], Any],
        on_success: Callable[[Any], None],
        error_title: str,
        log_prefix: str = "results task",
    ) -> None:
        if self._task_worker is not None and self._task_worker.isRunning():
            log.info("%s skipped | busy_action=%s next_action=%s", log_prefix, self._busy_action, action)
            return

        self._task_generation += 1
        generation = self._task_generation
        worker = ResultsTaskWorker(task)
        self._task_worker = worker
        self._set_busy(True, action=action)

        def _handle_success(payload: Any) -> None:
            self._finish_worker(worker)
            if generation != self._task_generation:
                return
            on_success(payload)

        def _handle_failure(error_text: str) -> None:
            self._finish_worker(worker)
            if generation != self._task_generation:
                return
            log.error("%s failed | action=%s\n%s", log_prefix, action, error_text)
            QMessageBox.critical(self, error_title, error_text)

        worker.succeeded.connect(_handle_success)
        worker.failed.connect(_handle_failure)
        worker.start()


__all__ = ["ResultTaskTabBase"]
