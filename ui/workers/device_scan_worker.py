from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class DeviceScanWorker(QThread):
    progress = Signal(int, int, str)
    result_found = Signal(dict)
    finished_scan = Signal(int)
    error = Signal(str)

    def __init__(self, discovery, timeout_ms: int = 1500):
        super().__init__()
        self.discovery = discovery
        self.timeout_ms = int(timeout_ms)
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            resources = list(self.discovery.scan_visa_resources())
        except Exception as e:
            self.error.emit(str(e))
            self.finished_scan.emit(0)
            return

        total = len(resources)
        emitted = 0
        for idx, resource in enumerate(resources, start=1):
            if self._cancel_requested:
                break
            self.progress.emit(idx, total, resource)
            try:
                row = self.discovery.identify_resource(resource, timeout_ms=self.timeout_ms)
            except Exception as e:
                row = {
                    "resource": resource,
                    "vendor": "",
                    "model": "",
                    "serial_number": "",
                    "idn": "",
                    "type": "",
                    "driver": "",
                    "status": f"ERROR: {e}",
                }
            self.result_found.emit(row)
            emitted += 1

        self.finished_scan.emit(emitted)
