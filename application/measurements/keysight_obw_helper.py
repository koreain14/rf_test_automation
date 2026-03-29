from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, Iterator, Tuple

log = logging.getLogger(__name__)


@dataclass
class KeysightObwConfig:
    center_freq_hz: float
    span_hz: float
    rbw_hz: float
    vbw_hz: float
    detector: str = "PEAK"
    trace_mode: str = "MAXHOLD"
    sweep_time_s: float = 0.1
    rbw_auto: bool = True
    vbw_auto: bool = True
    sweep_auto: bool = False
    avg_count: int = 20
    atten_db: float = 10.0
    ref_level_dbm: float = 10.0
    sweep_points: int = 1001


@dataclass
class AnalyzerDetection:
    usable: bool
    reason: str
    target: Any | None = None
    idn: str = ""
    source_class: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "usable": self.usable,
            "reason": self.reason,
            "target": self.target,
            "idn": self.idn,
            "source_class": self.source_class,
        }


DEFAULT_SPAN_HZ_MIN = 50_000_000.0
DEFAULT_RBW_HZ_MIN = 10_000.0
DEFAULT_RBW_HZ_MAX = 300_000.0
DEFAULT_SWEEP_TIME_S = 0.1
DEFAULT_AVG_COUNT = 3
DEFAULT_ATTEN_DB = 10.0
DEFAULT_REF_LEVEL_DBM = 10.0
DEFAULT_SWEEP_POINTS = 1001
DEFAULT_POLL_INTERVAL_S = 0.1
DEFAULT_MAX_WAIT_S = 60.0
DEFAULT_FETCH_POLL_TIMEOUT_MS = 500


def _iter_timeout_targets(obj: Any) -> Iterator[Any]:
    visited = set()
    queue = [obj]
    while queue:
        cur = queue.pop(0)
        if cur is None:
            continue
        ident = id(cur)
        if ident in visited:
            continue
        visited.add(ident)
        yield cur
        for attr in ("driver", "instrument", "device", "resource", "session", "analyzer", "_session", "inst"):
            if hasattr(cur, attr):
                try:
                    queue.append(getattr(cur, attr))
                except Exception:
                    pass


def _unwrap_scpi_capable(obj: Any) -> Any | None:
    if obj is None:
        return None
    visited = set()
    queue = [obj]
    while queue:
        cur = queue.pop(0)
        if cur is None:
            continue
        ident = id(cur)
        if ident in visited:
            continue
        visited.add(ident)
        if hasattr(cur, "query") and hasattr(cur, "write"):
            return cur
        for attr in ("instrument", "driver", "device", "resource", "session", "analyzer", "_session", "inst"):
            if hasattr(cur, attr):
                try:
                    queue.append(getattr(cur, attr))
                except Exception:
                    pass
    return None


def detect_keysight_xseries_analyzer(source: Any) -> Dict[str, Any]:
    target = _unwrap_scpi_capable(source)
    source_class = type(target).__name__ if target is not None else (type(source).__name__ if source is not None else "None")
    if target is None:
        return AnalyzerDetection(False, "no_scpi_capability", None, "", source_class).as_dict()
    is_connected = bool(getattr(target, "is_connected", False))
    if not is_connected:
        return AnalyzerDetection(False, "not_connected", target, "", source_class).as_dict()

    idn = ""
    try:
        if hasattr(target, "query_idn"):
            idn = str(target.query_idn() or "")
        else:
            idn = str(target.query("*IDN?") or "")
    except Exception:
        idn = ""

    blob = f"{source_class} {idn}".lower()
    looks_keysight = (
        "keysight" in blob
        or "agilent" in blob
        or "n9020" in blob
        or "n9030" in blob
        or "mxa" in blob
        or "pxa" in blob
    )
    if not looks_keysight:
        return AnalyzerDetection(False, "not_keysight_xseries", target, idn, source_class).as_dict()
    return AnalyzerDetection(True, "idn_match", target, idn, source_class).as_dict()


def is_keysight_xseries_analyzer(source: Any) -> bool:
    return bool(detect_keysight_xseries_analyzer(source).get("usable"))


def _mock_from_case(case: Any) -> Dict[str, Any]:
    bw_mhz = float(getattr(case, "bw_mhz", 20.0) or 20.0)
    limit = bw_mhz
    measured = max(round(bw_mhz * 0.90, 3), round(bw_mhz - 2.0, 3))
    margin = round(limit - measured, 3)
    verdict = "PASS" if margin >= 0 else "FAIL"
    return {
        "measured_value": measured,
        "limit_value": limit,
        "margin_db": margin,
        "measurement_unit": "MHz",
        "measurement_source": "mock",
        "backend_reason": "mock_fallback",
        "verdict": verdict,
    }


def _mock_from_config(cfg: KeysightObwConfig) -> Tuple[float, Dict[str, Any]]:
    span_mhz = float(cfg.span_hz) / 1e6
    measured = round(max(span_mhz * 0.45, 1.0), 6)
    raw = {
        "method": "mock_keysight",
        "center_freq_hz": float(cfg.center_freq_hz),
        "span_hz": float(cfg.span_hz),
        "rbw_hz": float(cfg.rbw_hz),
        "vbw_hz": float(cfg.vbw_hz),
        "rbw_auto": bool(cfg.rbw_auto),
        "vbw_auto": bool(cfg.vbw_auto),
        "sweep_auto": bool(cfg.sweep_auto),
        "sweep_time_s": float(cfg.sweep_time_s),
        "avg_count": int(cfg.avg_count),
        "atten_db": float(cfg.atten_db),
        "ref_level_dbm": float(cfg.ref_level_dbm),
        "detector": str(cfg.detector),
        "trace_mode": str(cfg.trace_mode),
        "sweep_points": int(cfg.sweep_points),
    }
    return measured, raw


def mock_obw_measurement(obj: Any):
    """
    Compatibility helper.

    - procedures.py passes a case-like object and expects a dict result.
    - obw_executor.py passes KeysightObwConfig and expects (measured_mhz, raw_dict).
    """
    if isinstance(obj, KeysightObwConfig):
        return _mock_from_config(obj)
    return _mock_from_case(obj)


def _safe_write(inst: Any, cmd: str) -> None:
    try:
        inst.write(cmd)
    except Exception:
        log.exception("keysight obw SCPI write failed | cmd=%s", cmd)
        raise


def _safe_query(inst: Any, cmd: str) -> str:
    try:
        return str(inst.query(cmd) or "").strip()
    except Exception:
        log.exception("keysight obw SCPI query failed | cmd=%s", cmd)
        raise


def _quiet_query(inst: Any, cmd: str) -> str:
    return str(inst.query(cmd) or "").strip()


@contextmanager
def _temporary_timeout(inst: Any, timeout_ms: int) -> Iterator[None]:
    changes = []
    for target in _iter_timeout_targets(inst):
        for attr in ("timeout_ms", "timeout"):
            if not hasattr(target, attr):
                continue
            try:
                previous = getattr(target, attr)
                setattr(target, attr, timeout_ms)
                changes.append((target, attr, previous))
            except Exception:
                pass
    try:
        yield
    finally:
        for target, attr, previous in reversed(changes):
            try:
                setattr(target, attr, previous)
            except Exception:
                pass


def _normalize_detector(value: Any) -> str:
    detector = str(value or "PEAK").strip().upper()
    aliases = {
        "POSITIVE": "POS",
        "POS": "POS",
        "NEGATIVE": "NEG",
        "NEG": "NEG",
        "PEAK": "PEAK",
        "SAMPLE": "SAMP",
        "SAMP": "SAMP",
        "RMS": "RMS",
        "AVERAGE": "AVER",
        "AVER": "AVER",
    }
    return aliases.get(detector, "PEAK")


def _normalize_trace_mode(value: Any) -> str:
    mode = str(value or "MAXHOLD").strip().upper().replace(" ", "")
    aliases = {
        "MAXHOLD": "MAXH",
        "MAXH": "MAXH",
        "AVERAGE": "AVER",
        "AVER": "AVER",
        "WRITE": "WRIT",
        "WRIT": "WRIT",
        "CLEARWRITE": "WRIT",
        "CLEAR/WRITE": "WRIT",
    }
    return aliases.get(mode, "WRIT")


def _parse_first_float(response: str) -> float:
    text = str(response or "").strip()
    if not text:
        raise ValueError("empty OBW response")
    token = text.split(",")[0].strip()
    return float(token)


def _parse_first_int(response: str) -> int:
    text = str(response or "").strip()
    if not text:
        raise ValueError("empty integer response")
    token = text.split(",")[0].strip()
    return int(token)


def _as_float(value: Any, default: float) -> float:
    try:
        if value in (None, ""):
            raise ValueError
        return float(value)
    except Exception:
        return float(default)


def _as_int(value: Any, default: int) -> int:
    try:
        if value in (None, ""):
            raise ValueError
        return int(value)
    except Exception:
        return int(default)


def _as_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on", "auto"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off", "manual"}:
        return False
    return bool(default)


def _format_scpi_bool(value: bool) -> str:
    return "ON" if value else "OFF"


def _format_scpi_value(value: float) -> str:
    return f"{float(value):g}"


def _hz_to_mhz(value_hz: float) -> float:
    return float(value_hz) / 1e6


def _resolve_hz(
    cfg: Dict[str, Any],
    *,
    hz_key: str,
    mhz_key: str,
    default_hz: float,
) -> float:
    if cfg.get(hz_key) not in (None, ""):
        return _as_float(cfg.get(hz_key), default_hz)
    if cfg.get(mhz_key) not in (None, ""):
        return _as_float(cfg.get(mhz_key), default_hz / 1e6) * 1e6
    return float(default_hz)


def _cfg_has_any(cfg: Dict[str, Any], *keys: str) -> bool:
    return any(cfg.get(key) not in (None, "") for key in keys)


def _build_runtime_config(case: Any) -> KeysightObwConfig:
    center_freq_mhz = _as_float(getattr(case, "center_freq_mhz", 0.0), 0.0)
    bw_mhz = _as_float(getattr(case, "bw_mhz", 20.0), 20.0)
    instrument_cfg = dict(getattr(case, "instrument", {}) or {})

    span_hz = _resolve_hz(
        instrument_cfg,
        hz_key="span_hz",
        mhz_key="span_mhz",
        default_hz=max(bw_mhz * 2.0e6, DEFAULT_SPAN_HZ_MIN),
    )
    rbw_hz = _resolve_hz(
        instrument_cfg,
        hz_key="rbw_hz",
        mhz_key="rbw_mhz",
        default_hz=max(min(span_hz / 100.0, DEFAULT_RBW_HZ_MAX), DEFAULT_RBW_HZ_MIN),
    )
    vbw_hz = _resolve_hz(
        instrument_cfg,
        hz_key="vbw_hz",
        mhz_key="vbw_mhz",
        default_hz=max(rbw_hz * 3.0, rbw_hz),
    )

    rbw_auto_default = not _cfg_has_any(instrument_cfg, "rbw_hz", "rbw_mhz")
    vbw_auto_default = not _cfg_has_any(instrument_cfg, "vbw_hz", "vbw_mhz")
    sweep_auto_default = False

    return KeysightObwConfig(
        center_freq_hz=center_freq_mhz * 1e6,
        span_hz=span_hz,
        rbw_hz=rbw_hz,
        vbw_hz=vbw_hz,
        detector=_normalize_detector(instrument_cfg.get("detector", "PEAK")),
        trace_mode=_normalize_trace_mode(instrument_cfg.get("trace_mode", "MAXHOLD")),
        sweep_time_s=_as_float(instrument_cfg.get("sweep_time_s"), DEFAULT_SWEEP_TIME_S),
        rbw_auto=_as_bool(instrument_cfg.get("rbw_auto"), rbw_auto_default),
        vbw_auto=_as_bool(instrument_cfg.get("vbw_auto"), vbw_auto_default),
        sweep_auto=_as_bool(instrument_cfg.get("sweep_auto"), sweep_auto_default),
        avg_count=max(1, _as_int(instrument_cfg.get("avg_count"), DEFAULT_AVG_COUNT)),
        atten_db=_as_float(
            instrument_cfg.get("atten_db", instrument_cfg.get("att_db")),
            DEFAULT_ATTEN_DB,
        ),
        ref_level_dbm=_as_float(instrument_cfg.get("ref_level_dbm"), DEFAULT_REF_LEVEL_DBM),
        sweep_points=max(101, _as_int(instrument_cfg.get("sweep_points"), DEFAULT_SWEEP_POINTS)),
    )


def _write_stage(inst: Any, stage: str, cmd: str) -> None:
    log.info("keysight obw SCPI write | stage=%s cmd=%s", stage, cmd)
    _safe_write(inst, cmd)


def _query_stage(inst: Any, stage: str, cmd: str) -> str:
    log.info("keysight obw SCPI query | stage=%s cmd=%s", stage, cmd)
    return _safe_query(inst, cmd)


def _estimated_wait_seconds(cfg: KeysightObwConfig, instrument_cfg: Dict[str, Any]) -> float:
    configured = instrument_cfg.get("measurement_wait_s")
    if configured not in (None, ""):
        return max(1.0, _as_float(configured, DEFAULT_MAX_WAIT_S))

    if cfg.sweep_auto:
        # Auto sweep can vary significantly by firmware and averaging setup.
        return max(10.0, float(cfg.avg_count) * 2.0)

    estimated = max(1.0, float(cfg.sweep_time_s)) * max(1.0, float(cfg.avg_count))
    return max(5.0, min(max(estimated * 3.0, 5.0), DEFAULT_MAX_WAIT_S))


def _estimated_fetch_poll_timeout_ms(instrument_cfg: Dict[str, Any], request_timeout_ms: int) -> int:
    configured = instrument_cfg.get("fetch_poll_timeout_ms")
    if configured not in (None, ""):
        return max(100, _as_int(configured, DEFAULT_FETCH_POLL_TIMEOUT_MS))
    return max(100, min(int(request_timeout_ms or DEFAULT_FETCH_POLL_TIMEOUT_MS), DEFAULT_FETCH_POLL_TIMEOUT_MS))


def _configure_obw_measurement(inst: Any, cfg: KeysightObwConfig) -> None:
    commands = [
        ("prepare", "*CLS"),
        ("prepare", ":INIT:CONT OFF"),
        ("prepare", ":ABOR"),
        ("mode", ":CONF:OBW"),
        ("average", ":OBW:AVER ON"),
        ("average", f":OBW:AVER:COUN {_as_int(cfg.avg_count, DEFAULT_AVG_COUNT)}"),
        ("frequency", f":FREQ:CENT {_format_scpi_value(_hz_to_mhz(cfg.center_freq_hz))}MHZ"),
        ("span", f":OBW:FREQ:SPAN {_format_scpi_value(_hz_to_mhz(cfg.span_hz))}MHZ"),
        ("rbw", f":OBW:BAND:RES {_format_scpi_value(_hz_to_mhz(cfg.rbw_hz))}MHZ"),
        ("vbw", f":OBW:BAND:VID {_format_scpi_value(_hz_to_mhz(cfg.vbw_hz))}MHZ"),
        ("rbw_auto", f":OBW:BAND:RES:AUTO {_format_scpi_bool(cfg.rbw_auto)}"),
        ("vbw_auto", f":OBW:BAND:VID:AUTO {_format_scpi_bool(cfg.vbw_auto)}"),
        ("sweep", f":OBW:SWE:TIME {_format_scpi_value(cfg.sweep_time_s)}S"),
        ("sweep_auto", f":OBW:SWE:TIME:AUTO {_format_scpi_bool(cfg.sweep_auto)}"),
        ("unit", ":UNIT:POW DBM"),
        ("sweep_points", f":SWE:POIN {_as_int(cfg.sweep_points, DEFAULT_SWEEP_POINTS)}"),
        ("atten", f":POW:ATT {_format_scpi_value(cfg.atten_db)}DB"),
        ("display", f":DISP:OBW:VIEW:WIND:TRAC:Y:RLEV {_format_scpi_value(cfg.ref_level_dbm)}DBM"),
        ("detector", f":OBW:DET {cfg.detector}"),
        ("trace", f":TRAC1:OBW:TYPE {cfg.trace_mode}"),
    ]
    for stage, cmd in commands:
        _write_stage(inst, stage, cmd)


def _fetch_obw_hz(inst: Any) -> float:
    responses: list[str] = []
    for stage, cmd in (
        ("result_fetch", ":FETC:OBW?"),
        ("result_legacy", ":CALC:MARK:FUNC:POW:RES? OBW"),
    ):
        try:
            log.info("keysight obw SCPI query | stage=%s cmd=%s", stage, cmd)
            response = _quiet_query(inst, cmd)
            responses.append(response)
            value = _parse_first_float(response)
            if value > 0:
                return value
        except Exception as exc:
            log.info("keysight obw result query pending | stage=%s cmd=%s err=%s", stage, cmd, exc)
    raise RuntimeError(f"unable to read OBW result from analyzer | responses={responses}")


def _poll_obw_result_hz(
    inst: Any,
    *,
    max_wait_s: float,
    fetch_poll_timeout_ms: int,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> float:
    deadline = time.monotonic() + max(0.5, float(max_wait_s))
    last_fetch_error = ""

    while time.monotonic() < deadline:
        try:
            with _temporary_timeout(inst, fetch_poll_timeout_ms):
                value = _fetch_obw_hz(inst)
            log.info(
                "keysight obw result detected | max_wait_s=%s fetch_poll_timeout_ms=%s value_hz=%s",
                max_wait_s,
                fetch_poll_timeout_ms,
                value,
            )
            return value
        except Exception as exc:
            last_fetch_error = str(exc)
            log.info(
                "keysight obw result not ready yet | max_wait_s=%s fetch_poll_timeout_ms=%s err=%s",
                max_wait_s,
                fetch_poll_timeout_ms,
                exc,
            )
        time.sleep(max(0.01, float(poll_interval_s)))

    raise RuntimeError(
        "OBW measurement did not complete before deadline | "
        f"max_wait_s={max_wait_s} fetch_poll_timeout_ms={fetch_poll_timeout_ms} "
        f"last_fetch_error={last_fetch_error}"
    )


def _acquire_obw_hz(inst: Any, *, max_wait_s: float, fetch_poll_timeout_ms: int) -> float:
    _write_stage(inst, "init", ":INIT:IMM")
    return _poll_obw_result_hz(
        inst,
        max_wait_s=max_wait_s,
        fetch_poll_timeout_ms=fetch_poll_timeout_ms,
    )


def measure_obw_keysight(source: Any, case: Any, *, timeout_ms: int = 5000, retries: int = 1) -> Dict[str, Any]:
    detection = detect_keysight_xseries_analyzer(source)
    if not detection.get("usable"):
        raise RuntimeError(f"Keysight analyzer unavailable: {detection.get('reason', 'unknown')}")

    inst = detection["target"]
    cfg = _build_runtime_config(case)
    bw_mhz = _as_float(getattr(case, "bw_mhz", 20.0), 20.0)
    instrument_cfg = dict(getattr(case, "instrument", {}) or {})
    max_wait_s = _estimated_wait_seconds(cfg, instrument_cfg)
    fetch_poll_timeout_ms = _estimated_fetch_poll_timeout_ms(instrument_cfg, timeout_ms)

    last_exc = None
    last_stage = "startup"
    for attempt in range(1, retries + 1):
        try:
            log.info(
                "keysight obw measurement start | attempt=%s/%s timeout_ms=%s max_wait_s=%s fetch_poll_timeout_ms=%s cf_mhz=%s span_mhz=%s rbw_auto=%s rbw_mhz=%s vbw_auto=%s vbw_mhz=%s sweep_auto=%s sweep_time_s=%s atten_db=%s ref_level_dbm=%s detector=%s avg_count=%s trace_mode=%s",
                attempt,
                retries,
                timeout_ms,
                max_wait_s,
                fetch_poll_timeout_ms,
                _hz_to_mhz(cfg.center_freq_hz),
                _hz_to_mhz(cfg.span_hz),
                cfg.rbw_auto,
                _hz_to_mhz(cfg.rbw_hz),
                cfg.vbw_auto,
                _hz_to_mhz(cfg.vbw_hz),
                cfg.sweep_auto,
                cfg.sweep_time_s,
                cfg.atten_db,
                cfg.ref_level_dbm,
                cfg.detector,
                cfg.avg_count,
                cfg.trace_mode,
            )
            with _temporary_timeout(inst, timeout_ms):
                last_stage = "configure"
                _configure_obw_measurement(inst, cfg)
                last_stage = "acquire"
                measured_hz = _acquire_obw_hz(
                    inst,
                    max_wait_s=max_wait_s,
                    fetch_poll_timeout_ms=fetch_poll_timeout_ms,
                )

            measured_mhz = round(measured_hz / 1e6, 6)
            limit = bw_mhz
            margin = round(limit - measured_mhz, 6)
            verdict = "PASS" if margin >= 0 else "FAIL"
            return {
                "measured_value": measured_mhz,
                "limit_value": limit,
                "margin_db": margin,
                "measurement_unit": "MHz",
                "measurement_source": "keysight_xseries_scpi",
                "backend_reason": detection.get("reason", "idn_match"),
                "backend_idn": detection.get("idn", ""),
                "scpi_timeout_ms": int(timeout_ms),
                "scpi_max_wait_s": float(max_wait_s),
                "scpi_fetch_poll_timeout_ms": int(fetch_poll_timeout_ms),
                "scpi_trace_mode": cfg.trace_mode,
                "scpi_detector": cfg.detector,
                "scpi_avg_count": int(cfg.avg_count),
                "scpi_rbw_auto": bool(cfg.rbw_auto),
                "scpi_vbw_auto": bool(cfg.vbw_auto),
                "scpi_sweep_auto": bool(cfg.sweep_auto),
                "verdict": verdict,
            }
        except Exception as exc:
            last_exc = exc
            log.warning(
                "keysight obw measurement failed | attempt=%s/%s stage=%s timeout_ms=%s err=%s",
                attempt,
                retries,
                last_stage,
                timeout_ms,
                exc,
            )

    raise RuntimeError(f"Keysight OBW SCPI measurement failed at stage={last_stage}: {last_exc}")
