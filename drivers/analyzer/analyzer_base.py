from __future__ import annotations

from typing import Any, Dict

from drivers.common.pyvisa_device_base import PyVisaDeviceBase


class AnalyzerBase(PyVisaDeviceBase):
    def reset(self) -> None:
        if self.is_connected:
            self.write("*RST")

    def configure(self, settings: Dict[str, Any]) -> None:
        if not self.is_connected:
            return
        command_map = {
            "center_freq_hz": ":FREQ:CENT {value}",
            "span_hz": ":FREQ:SPAN {value}",
            "rbw_hz": ":BAND {value}",
            "vbw_hz": ":BAND:VID {value}",
            "sweep_time_s": ":SWE:TIME {value}",
            "ref_level_dbm": ":DISP:WIND:TRAC:Y:RLEV {value}",
        }
        for key, template in command_map.items():
            if key in settings and settings[key] not in (None, ""):
                try:
                    self.write(template.format(value=settings[key]))
                except Exception:
                    pass

    def get_trace(self) -> Dict[str, Any]:
        if not self.is_connected:
            return {"trace": [], "source": "DISCONNECTED"}
        try:
            raw = self.query(":TRAC? TRACE1")
            return {"trace": raw, "source": "SCPI"}
        except Exception as e:
            return {"trace": [], "source": "ERROR", "error": str(e)}
