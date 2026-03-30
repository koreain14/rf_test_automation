from __future__ import annotations

import logging
from typing import Any, Dict, Optional


log = logging.getLogger(__name__)


class SCPIInstrumentDriver:
    """SCPI analyzer driver with optional pyvisa transport.

    Behavior in V8:
    - If pyvisa is installed and `connect()` succeeds, the driver can perform
      real write/query calls through the VISA session.
    - If pyvisa is missing or the connection fails, the driver stays in a
      disconnected/simulated state but preserves the public interface so the
      rest of the app keeps working.
    """

    def __init__(self, resource_name: str, timeout_ms: int = 10000):
        self.resource_name = resource_name
        self.timeout_ms = timeout_ms
        self._session: Optional[Any] = None
        self._rm: Optional[Any] = None
        self._last_settings: Dict[str, Any] = {}
        self._connect_error: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    @property
    def last_connect_error(self) -> Optional[str]:
        return self._connect_error

    def connect(self) -> None:
        self._connect_error = None
        try:
            import pyvisa  # type: ignore

            self._rm = pyvisa.ResourceManager()
            self._session = self._rm.open_resource(self.resource_name)
            try:
                self._session.timeout = self.timeout_ms
            except Exception:
                pass
        except Exception as e:
            self._session = None
            self._rm = None
            self._connect_error = str(e)

    def disconnect(self) -> None:
        try:
            if self._session is not None and hasattr(self._session, "close"):
                self._session.close()
        except Exception:
            pass

        try:
            if self._rm is not None and hasattr(self._rm, "close"):
                self._rm.close()
        except Exception:
            pass

        self._session = None
        self._rm = None

    def write(self, command: str) -> None:
        if self._session is None:
            raise RuntimeError(
                f"SCPI instrument is not connected: {self._connect_error or self.resource_name}"
            )
        log.info(
            "scpi driver write | driver=%s resource=%s command=%s",
            type(self).__name__,
            self.resource_name,
            command,
        )
        self._session.write(command)

    def query(self, command: str) -> str:
        if self._session is None:
            raise RuntimeError(
                f"SCPI instrument is not connected: {self._connect_error or self.resource_name}"
            )
        log.info(
            "scpi driver query | driver=%s resource=%s command=%s",
            type(self).__name__,
            self.resource_name,
            command,
        )
        response = str(self._session.query(command))
        log.info(
            "scpi driver query response | driver=%s resource=%s command=%s response=%s",
            type(self).__name__,
            self.resource_name,
            command,
            response.strip(),
        )
        return response

    def configure(self, settings: Dict[str, Any]) -> None:
        self._last_settings = dict(settings)
        if self._session is None:
            return

        command_map = {
            "center_freq_hz": ":FREQ:CENT {value}",
            "span_hz": ":FREQ:SPAN {value}",
            "rbw_hz": ":BAND {value}",
            "vbw_hz": ":BAND:VID {value}",
            "sweep_time_s": ":SWE:TIME {value}",
            "ref_level_dbm": ":DISP:WIND:TRAC:Y:RLEV {value}",
            "att_db": ":POW:ATT {value}",
        }
        for key, template in command_map.items():
            if key in settings and settings[key] not in (None, ""):
                try:
                    self.write(template.format(value=settings[key]))
                except Exception:
                    # Leave room for vendor-specific handling later.
                    pass

    def acquire_trace(self) -> Dict[str, Any]:
        if self._session is None:
            return {
                "trace": [],
                "settings": dict(self._last_settings),
                "source": "SCPI-DISCONNECTED",
                "connect_error": self._connect_error,
            }

        try:
            raw = self.query(":TRAC? TRACE1")
            return {
                "trace": raw,
                "settings": dict(self._last_settings),
                "source": "SCPI",
            }
        except Exception as e:
            return {
                "trace": [],
                "settings": dict(self._last_settings),
                "source": "SCPI-ERROR",
                "error": str(e),
            }
