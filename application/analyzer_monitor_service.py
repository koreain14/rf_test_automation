from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AnalyzerMonitorRequest:
    center_freq_mhz: float
    bandwidth_mhz: float
    phy_mode: str = ""
    span_hz: float | None = None
    rbw_hz: float = 100_000.0
    vbw_hz: float | None = None
    ref_level_dbm: float = 10.0


@dataclass
class AnalyzerMonitorResult:
    ok: bool
    status: str
    message: str
    source: str
    center_freq_mhz: float | None = None
    bandwidth_mhz: float | None = None
    span_mhz: float | None = None


class AnalyzerMonitorService:
    """Best-effort analyzer preview/monitor preset application.

    This service is intentionally separate from formal measurements. It only
    prepares the analyzer so the user can visually confirm signal presence on
    the front panel during the DUT reconfiguration dialog.
    """

    def build_request(self, payload: dict[str, Any]) -> AnalyzerMonitorRequest:
        current = dict(payload.get("current") or {})
        center_freq_mhz = self._safe_float(current.get("center_freq_mhz"), 0.0)
        bandwidth_mhz = self._safe_float(current.get("bw_mhz"), 0.0)
        phy_mode = str(current.get("phy_mode") or payload.get("standard") or "")
        span_hz = self._default_span_hz(bandwidth_mhz)
        vbw_hz = max(1000.0, self._safe_float(span_hz / 3.0, 300_000.0))
        return AnalyzerMonitorRequest(
            center_freq_mhz=center_freq_mhz,
            bandwidth_mhz=bandwidth_mhz,
            phy_mode=phy_mode,
            span_hz=span_hz,
            rbw_hz=100_000.0,
            vbw_hz=vbw_hz,
            ref_level_dbm=10.0,
        )

    def start_monitor(self, instrument: Any, payload: dict[str, Any]) -> AnalyzerMonitorResult:
        request = self.build_request(payload)
        if request.center_freq_mhz <= 0:
            return AnalyzerMonitorResult(
                ok=False,
                status="UNAVAILABLE",
                message="Monitor unavailable: current channel frequency is not available.",
                source="INVALID",
            )

        if instrument is None:
            return AnalyzerMonitorResult(
                ok=False,
                status="UNAVAILABLE",
                message="Monitor unavailable: no active analyzer session is available.",
                source="NO_INSTRUMENT",
                center_freq_mhz=request.center_freq_mhz,
                bandwidth_mhz=request.bandwidth_mhz,
                span_mhz=float(request.span_hz or 0.0) / 1_000_000.0,
            )

        settings = {
            "center_freq_hz": request.center_freq_mhz * 1_000_000.0,
            "span_hz": float(request.span_hz or self._default_span_hz(request.bandwidth_mhz)),
            "rbw_hz": float(request.rbw_hz),
            "vbw_hz": float(request.vbw_hz or request.rbw_hz),
            "ref_level_dbm": float(request.ref_level_dbm),
        }

        try:
            if hasattr(instrument, "write"):
                self._safe_write(instrument, ":CONF:SAN")

            if hasattr(instrument, "configure"):
                instrument.configure(settings)

            if hasattr(instrument, "write"):
                self._safe_write(instrument, ":INIT:CONT ON")
                self._safe_write(instrument, ":TRAC1:MODE WRIT")
                self._safe_write(instrument, ":DET POS")

            source = type(instrument).__name__
            if source.upper().startswith("DUMMY"):
                status = "ACTIVE"
                message = (
                    "Monitor preview active on dummy analyzer path. "
                    "Use this for flow validation only."
                )
            else:
                status = "ACTIVE"
                message = (
                    "Monitor preview active. Analyzer is set to center/span preview mode "
                    "for visual signal confirmation."
                )

            return AnalyzerMonitorResult(
                ok=True,
                status=status,
                message=message,
                source=source,
                center_freq_mhz=request.center_freq_mhz,
                bandwidth_mhz=request.bandwidth_mhz,
                span_mhz=float(settings["span_hz"]) / 1_000_000.0,
            )
        except Exception as exc:
            return AnalyzerMonitorResult(
                ok=False,
                status="ERROR",
                message=f"Monitor preset failed: {exc}",
                source=type(instrument).__name__,
                center_freq_mhz=request.center_freq_mhz,
                bandwidth_mhz=request.bandwidth_mhz,
                span_mhz=float(request.span_hz or 0.0) / 1_000_000.0,
            )

    def _safe_write(self, instrument: Any, cmd: str) -> None:
        try:
            instrument.write(cmd)
        except Exception:
            pass

    def _default_span_hz(self, bandwidth_mhz: float) -> float:
        bw = max(0.0, float(bandwidth_mhz or 0.0))
        return max(20_000_000.0, bw * 2.0 * 1_000_000.0)

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)
