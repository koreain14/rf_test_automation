from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal


class ResultsTaskWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], Any]):
        super().__init__()
        self._task = task

    def run(self) -> None:
        try:
            result = self._task()
        except Exception:
            self.failed.emit(traceback.format_exc())
            return
        self.succeeded.emit(result)
