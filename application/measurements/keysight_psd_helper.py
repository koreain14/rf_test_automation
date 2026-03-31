from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, Iterator

from application.analyzer_screenshot import capture_analyzer_screenshot_best_effort
from application.measurement_profile_runtime import build_consumable_measurement_profile
from application.measurements.keysight_obw_helper import detect_keysight_xseries_analyzer
from application.psd_unit_policy import (
    PSD_CANONICAL_UNIT,
    PSD_DEFAULT_LIMIT_CANONICAL,
    PSD_DEFAULT_SPAN_MULTIPLIER,
    PSD_METHOD_AVERAGE,
    PSD_METHOD_MARKER_PEAK,
    build_psd_display_payload,
    convert_psd_value,
    normalize_psd_method,
    normalize_psd_result_unit,
    psd_scpi_power_unit,
    psd_unit_label,
)


log = logging.getLogger(__name__)


@dataclass
class KeysightPsdConfig:
    center_freq_hz: float
    span_hz: float
    rbw_hz: float
    vbw_hz: float
    detector: str = "RMS"
    trace_mode: str = "AVER"
    sweep_time_s: float = 0.1
    average_enabled: bool = False
    avg_count: int = 1
    atten_db: float = 10.0
    ref_level_dbm: float = 20.0


DEFAULT_SPAN_HZ_MIN = 20_000_000.0
DEFAULT_RBW_HZ_MIN = 1_000.0
DEFAULT_RBW_HZ_MAX = 300_000.0
DEFAULT_SWEEP_TIME_S = 0.1
DEFAULT_AVG_COUNT = 1
DEFAULT_ATTEN_DB = 10.0
DEFAULT_REF_LEVEL_DBM = 20.0
DEFAULT_MODE_SETTLE_S = 0.05
DEFAULT_POST_CONFIG_SETTLE_S = 0.02
DEFAULT_POST_INIT_SETTLE_S = 0.05


def _psd_unit_label(unit: str) -> str:
    return psd_unit_label(unit)


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


def _safe_write(inst: Any, cmd: str) -> None:
    inst.write(cmd)


def _safe_query(inst: Any, cmd: str) -> str:
    return str(inst.query(cmd) or "").strip()


def _read_system_error_best_effort(inst: Any) -> str:
    try:
        return str(inst.query("SYST:ERR?") or "").strip()
    except Exception:
        return ""


class _temporary_timeout:
    def __init__(self, inst: Any, timeout_ms: int):
        self.inst = inst
        self.timeout_ms = timeout_ms
        self.changes: list[tuple[Any, str, Any]] = []

    def __enter__(self):
        for target in _iter_timeout_targets(self.inst):
            for attr in ("timeout_ms", "timeout"):
                if not hasattr(target, attr):
                    continue
                try:
                    previous = getattr(target, attr)
                    setattr(target, attr, self.timeout_ms)
                    self.changes.append((target, attr, previous))
                except Exception:
                    pass
        return None

    def __exit__(self, exc_type, exc, tb):
        for target, attr, previous in reversed(self.changes):
            try:
                setattr(target, attr, previous)
            except Exception:
                pass
        return False


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
    if text in {"1", "true", "t", "yes", "y", "on", "auto", "enabled"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off", "manual", "disabled"}:
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


def _normalize_detector(value: Any) -> str:
    detector = str(value or "RMS").strip().upper()
    aliases = {
        "POSITIVE": "POS",
        "POS": "POS",
        "PEAK": "POS",
        "NEGATIVE": "NEG",
        "NEG": "NEG",
        "SAMPLE": "SAMP",
        "SAMP": "SAMP",
        "RMS": "RMS",
        "AVERAGE": "AVER",
        "AVER": "AVER",
    }
    return aliases.get(detector, "RMS")


def _normalize_trace_mode(value: Any) -> str:
    mode = str(value or "AVERAGE").strip().upper().replace(" ", "").replace("_", "").replace("/", "")
    aliases = {
        "MAXHOLD": "MAXH",
        "MAXH": "MAXH",
        "AVERAGE": "AVER",
        "AVER": "AVER",
        "WRITE": "WRIT",
        "WRIT": "WRIT",
        "CLEARWRITE": "WRIT",
    }
    return aliases.get(mode, "AVER")


def _settle_seconds_from_cfg(cfg: Dict[str, Any], key: str, default: float) -> float:
    return max(0.0, _as_float(cfg.get(key), default))


def _write_stage(inst: Any, stage: str, cmd: str) -> None:
    log.info("keysight psd SCPI write | stage=%s cmd=%s", stage, cmd)
    try:
        _safe_write(inst, cmd)
    except Exception:
        system_error = _read_system_error_best_effort(inst)
        log.exception("keysight psd SCPI write failed | stage=%s cmd=%s system_error=%s", stage, cmd, system_error)
        raise


def _query_stage(inst: Any, stage: str, cmd: str) -> str:
    log.info("keysight psd SCPI query | stage=%s cmd=%s", stage, cmd)
    try:
        return _safe_query(inst, cmd)
    except Exception:
        system_error = _read_system_error_best_effort(inst)
        log.exception("keysight psd SCPI query failed | stage=%s cmd=%s system_error=%s", stage, cmd, system_error)
        raise


def _sync_stage(inst: Any, stage: str, *, fallback_sleep_s: float = 0.0) -> None:
    try:
        response = _query_stage(inst, f"{stage}_opc", "*OPC?")
        log.info("keysight psd SCPI sync | stage=%s opc=%s", stage, response)
        return
    except Exception as exc:
        log.info(
            "keysight psd SCPI sync fallback | stage=%s fallback_sleep_s=%s err=%s",
            stage,
            fallback_sleep_s,
            exc,
        )
    if fallback_sleep_s > 0.0:
        time.sleep(float(fallback_sleep_s))


def _best_effort_query_candidates(inst: Any, *, stage: str, commands: tuple[str, ...]) -> tuple[str, str]:
    last_error = ""
    for cmd in commands:
        try:
            response = _query_stage(inst, stage, cmd)
            return cmd, response
        except Exception as exc:
            last_error = str(exc)
            log.info(
                "keysight psd SCPI readback candidate failed | stage=%s cmd=%s err=%s",
                stage,
                cmd,
                exc,
            )
    return "", last_error


def _log_psd_apply_readback(inst: Any) -> None:
    trace_cmd, trace_response = _best_effort_query_candidates(
        inst,
        stage="trace_readback",
        commands=(
            ":TRAC1:MODE?",
            ":TRAC:MODE?",
        ),
    )
    detector_cmd, detector_response = _best_effort_query_candidates(
        inst,
        stage="detector_readback",
        commands=(
            ":DET?",
        ),
    )
    average_cmd, average_response = _best_effort_query_candidates(
        inst,
        stage="average_readback",
        commands=(
            ":AVER?",
        ),
    )
    avg_count_cmd, avg_count_response = _best_effort_query_candidates(
        inst,
        stage="average_count_readback",
        commands=(
            ":AVER:COUN?",
        ),
    )
    unit_cmd, unit_response = _best_effort_query_candidates(
        inst,
        stage="unit_readback",
        commands=(
            ":UNIT:POW?",
        ),
    )
    log.info(
        "keysight psd apply readback | trace_cmd=%s trace_response=%s detector_cmd=%s detector_response=%s average_cmd=%s average_response=%s avg_count_cmd=%s avg_count_response=%s unit_cmd=%s unit_response=%s",
        trace_cmd,
        trace_response,
        detector_cmd,
        detector_response,
        average_cmd,
        average_response,
        avg_count_cmd,
        avg_count_response,
        unit_cmd,
        unit_response,
    )


def _build_runtime_config(case: Any, profile_settings: Dict[str, Any] | None = None) -> tuple[KeysightPsdConfig, Dict[str, Any]]:
    center_freq_mhz = _as_float(getattr(case, "center_freq_mhz", 0.0), 0.0)
    bw_mhz = _as_float(getattr(case, "bw_mhz", 20.0), 20.0)
    instrument_cfg = build_consumable_measurement_profile(
        test_type=getattr(case, "test_type", ""),
        resolved_profile=dict(profile_settings or {}),
        instrument_snapshot=dict(getattr(case, "instrument", {}) or {}),
    )
    measurement_field_sources = dict(instrument_cfg.get("measurement_field_sources") or {})
    resolved_profile_span_source = str(
        measurement_field_sources.get("span_hz")
        or measurement_field_sources.get("span_mhz")
        or ""
    ).strip()
    default_span_hz = max(bw_mhz * PSD_DEFAULT_SPAN_MULTIPLIER * 1.0e6, DEFAULT_SPAN_HZ_MIN)
    if resolved_profile_span_source == "profile_override":
        span_hz = _resolve_hz(
            instrument_cfg,
            hz_key="span_hz",
            mhz_key="span_mhz",
            default_hz=default_span_hz,
        )
        applied_span_source = "profile_override"
    else:
        span_hz = float(default_span_hz)
        applied_span_source = "computed_default"
    rbw_hz = _resolve_hz(
        instrument_cfg,
        hz_key="rbw_hz",
        mhz_key="rbw_mhz",
        default_hz=max(min(span_hz / 1000.0, DEFAULT_RBW_HZ_MAX), DEFAULT_RBW_HZ_MIN),
    )
    vbw_hz = _resolve_hz(
        instrument_cfg,
        hz_key="vbw_hz",
        mhz_key="vbw_mhz",
        default_hz=max(rbw_hz * 3.0, rbw_hz),
    )
    raw_detector = instrument_cfg.get("detector", "RMS")
    raw_trace_mode = instrument_cfg.get("trace_mode", "AVERAGE")
    normalized_detector = _normalize_detector(raw_detector)
    normalized_trace_mode = _normalize_trace_mode(raw_trace_mode)
    average_enabled = _as_bool(
        instrument_cfg.get("average_enabled", instrument_cfg.get("average")),
        _as_int(instrument_cfg.get("avg_count"), DEFAULT_AVG_COUNT) > 1,
    )
    instrument_cfg = dict(instrument_cfg)
    instrument_cfg["resolved_profile_span_source"] = resolved_profile_span_source or "none"
    instrument_cfg["resolved_span_source"] = applied_span_source
    instrument_cfg["resolved_span_hz"] = span_hz
    instrument_cfg["resolved_default_span_hz"] = default_span_hz

    log.info(
        "keysight psd profile normalization | case=%s test_type=%s profile_name=%s profile_source=%s raw_trace_mode=%s normalized_trace_mode=%s raw_detector=%s normalized_detector=%s average_enabled=%s avg_count=%s profile_span_source=%s applied_span_source=%s bw_mhz=%s span_hz=%s default_span_hz=%s rbw_hz=%s vbw_hz=%s",
        getattr(case, "key", ""),
        getattr(case, "test_type", ""),
        instrument_cfg.get("profile_name", ""),
        instrument_cfg.get("profile_source", ""),
        raw_trace_mode,
        normalized_trace_mode,
        raw_detector,
        normalized_detector,
        average_enabled,
        _as_int(instrument_cfg.get("avg_count"), DEFAULT_AVG_COUNT),
        instrument_cfg["resolved_profile_span_source"],
        applied_span_source,
        bw_mhz,
        span_hz,
        default_span_hz,
        rbw_hz,
        vbw_hz,
    )

    return (
        KeysightPsdConfig(
            center_freq_hz=center_freq_mhz * 1e6,
            span_hz=span_hz,
            rbw_hz=rbw_hz,
            vbw_hz=vbw_hz,
            detector=normalized_detector,
            trace_mode=normalized_trace_mode,
            sweep_time_s=_as_float(instrument_cfg.get("sweep_time_s"), DEFAULT_SWEEP_TIME_S),
            average_enabled=average_enabled,
            avg_count=max(1, _as_int(instrument_cfg.get("avg_count"), DEFAULT_AVG_COUNT)),
            atten_db=_as_float(
                instrument_cfg.get("atten_db", instrument_cfg.get("att_db")),
                DEFAULT_ATTEN_DB,
            ),
            ref_level_dbm=_as_float(instrument_cfg.get("ref_level_dbm"), DEFAULT_REF_LEVEL_DBM),
        ),
        instrument_cfg,
    )


def _resolve_display_unit(case: Any) -> str:
    tags = dict(getattr(case, "tags", {}) or {})
    return normalize_psd_result_unit(tags.get("psd_result_unit")) or PSD_CANONICAL_UNIT


def _resolve_policy_context(case: Any) -> Dict[str, Any]:
    tags = dict(getattr(case, "tags", {}) or {})
    display_unit = _resolve_display_unit(case)
    limit_value_raw = tags.get("psd_limit_value")
    limit_unit = normalize_psd_result_unit(tags.get("psd_limit_unit")) or display_unit
    try:
        limit_value = float(limit_value_raw) if limit_value_raw not in (None, "") else convert_psd_value(
            PSD_DEFAULT_LIMIT_CANONICAL,
            from_unit=PSD_CANONICAL_UNIT,
            to_unit=limit_unit,
        )
    except Exception:
        limit_value = convert_psd_value(
            PSD_DEFAULT_LIMIT_CANONICAL,
            from_unit=PSD_CANONICAL_UNIT,
            to_unit=limit_unit,
        )
    canonical_limit_value = tags.get("psd_canonical_limit_value")
    try:
        canonical_limit = (
            float(canonical_limit_value)
            if canonical_limit_value not in (None, "")
            else convert_psd_value(limit_value, from_unit=limit_unit, to_unit=PSD_CANONICAL_UNIT)
        )
    except Exception:
        canonical_limit = convert_psd_value(limit_value, from_unit=limit_unit, to_unit=PSD_CANONICAL_UNIT)
    return {
        "ruleset_id": str(tags.get("ruleset_id", "") or ""),
        "band": str(getattr(case, "band", "") or tags.get("band", "") or ""),
        "device_class": str(tags.get("device_class", "") or ""),
        "measurement_profile_name": str(tags.get("measurement_profile_name", "") or ""),
        "display_unit": display_unit,
        "display_unit_label": _psd_unit_label(display_unit),
        "scpi_power_unit": psd_scpi_power_unit(display_unit),
        "method": normalize_psd_method(tags.get("psd_method")) or PSD_METHOD_MARKER_PEAK,
        "policy_source": str(tags.get("psd_unit_policy_source", "") or ""),
        "ruleset_limit_value": float(limit_value),
        "ruleset_limit_unit": limit_unit,
        "ruleset_limit_label": _psd_unit_label(limit_unit),
        "canonical_limit_value": float(canonical_limit),
    }


def _configure_psd_measurement(
    inst: Any,
    cfg: KeysightPsdConfig,
    *,
    scpi_power_unit: str = "DBM",
    mode_settle_s: float = DEFAULT_MODE_SETTLE_S,
    post_config_settle_s: float = DEFAULT_POST_CONFIG_SETTLE_S,
) -> None:
    commands = [
        ("prepare", "*CLS"),
        # Use single-shot acquisition so marker read does not restart averaging unexpectedly.
        ("prepare", ":INIT:CONT OFF"),
        ("prepare", ":ABOR"),
        ("prepare", ":CONF:SAN"),
        ("frequency", f":FREQ:CENT {_format_scpi_value(cfg.center_freq_hz)}"),
        ("span", f":FREQ:SPAN {_format_scpi_value(cfg.span_hz)}"),
        ("rbw", f":BAND {_format_scpi_value(cfg.rbw_hz)}"),
        ("vbw", f":BAND:VID {_format_scpi_value(cfg.vbw_hz)}"),
        ("sweep", f":SWE:TIME {_format_scpi_value(cfg.sweep_time_s)}"),
        ("atten", f":POW:ATT {_format_scpi_value(cfg.atten_db)}"),
        ("unit", f":UNIT:POW {scpi_power_unit}"),
        ("display", f":DISP:WIND:TRAC:Y:RLEV {_format_scpi_value(cfg.ref_level_dbm)}"),
        ("average", f":AVER {_format_scpi_bool(cfg.average_enabled)}"),
        ("trace", f":TRAC1:MODE {cfg.trace_mode}"),
        ("detector", f":DET {cfg.detector}"),
    ]
    if cfg.average_enabled:
        commands.insert(12, ("average_count", f":AVER:COUN {_as_int(cfg.avg_count, DEFAULT_AVG_COUNT)}"))

    log.info(
        "keysight psd configure apply | trace_mode=%s detector=%s average_enabled=%s avg_count=%s center_freq_hz=%s span_hz=%s rbw_hz=%s vbw_hz=%s sweep_time_s=%s atten_db=%s ref_level_dbm=%s scpi_power_unit=%s mode_settle_s=%s post_config_settle_s=%s",
        cfg.trace_mode,
        cfg.detector,
        cfg.average_enabled,
        cfg.avg_count,
        cfg.center_freq_hz,
        cfg.span_hz,
        cfg.rbw_hz,
        cfg.vbw_hz,
        cfg.sweep_time_s,
        cfg.atten_db,
        cfg.ref_level_dbm,
        scpi_power_unit,
        mode_settle_s,
        post_config_settle_s,
    )

    for stage, cmd in commands:
        _write_stage(inst, stage, cmd)
        if cmd == ":ABOR":
            _sync_stage(inst, "post_abort", fallback_sleep_s=mode_settle_s)
    _sync_stage(inst, "post_psd_config", fallback_sleep_s=post_config_settle_s)
    _log_psd_apply_readback(inst)


def _parse_trace_points(response: str) -> list[float]:
    text = str(response or "").strip()
    if not text:
        return []
    points: list[float] = []
    for token in text.replace("\n", ",").split(","):
        stripped = token.strip()
        if not stripped:
            continue
        try:
            points.append(float(stripped))
        except Exception:
            continue
    return points


def _fetch_trace(inst: Any) -> list[float]:
    responses: list[str] = []
    for stage, cmd in (
        ("trace_fetch", ":TRAC? TRACE1"),
        ("trace_data_fetch", ":TRAC:DATA? TRACE1"),
    ):
        try:
            response = _query_stage(inst, stage, cmd)
            responses.append(response)
            points = _parse_trace_points(response)
            if points:
                return points
        except Exception as exc:
            responses.append(f"ERR:{exc}")
            log.info("keysight psd trace query pending | stage=%s cmd=%s err=%s", stage, cmd, exc)
    raise RuntimeError(f"unable to read PSD trace from analyzer | responses={responses}")


def _trigger_single_sweep(
    inst: Any,
    *,
    post_init_settle_s: float = DEFAULT_POST_INIT_SETTLE_S,
) -> None:
    log.info("keysight psd acquisition trigger | mode=single_sweep cmd=:INIT:IMM")
    _write_stage(inst, "init", ":INIT:IMM")
    _sync_stage(inst, "post_init", fallback_sleep_s=post_init_settle_s)


def _acquire_marker_peak_value(
    inst: Any,
    *,
    post_init_settle_s: float = DEFAULT_POST_INIT_SETTLE_S,
) -> Dict[str, Any]:
    _trigger_single_sweep(inst, post_init_settle_s=post_init_settle_s)
    try:
        _write_stage(inst, "marker_on", ":CALC:MARK1:STAT ON")
    except Exception as exc:
        log.info("keysight psd marker enable write skipped | err=%s", exc)
    try:
        # Marker operations are applied after the single sweep completes so averaging state is preserved.
        _write_stage(inst, "marker_mode", ":CALC:MARK1:MODE POS")
    except Exception as exc:
        log.info("keysight psd marker mode write skipped | err=%s", exc)
    try:
        _write_stage(inst, "marker_max", ":CALC:MARK1:MAX")
        marker_cmd, marker_response = _best_effort_query_candidates(
            inst,
            stage="marker_y_readback",
            commands=(
                ":CALC:MARK1:Y?",
                ":CALC:MARK:Y?",
            ),
        )
        if marker_cmd and marker_response not in (None, ""):
            value = float(marker_response.split(",")[0].strip())
            return {
                "measured_value": value,
                "trace_point_count": 0,
                "read_path": "marker_y",
                "read_command": marker_cmd,
            }
    except Exception as exc:
        log.info("keysight psd marker read failed -> fallback trace max | err=%s", exc)
    trace_points = _fetch_trace(inst)
    return {
        "measured_value": max(trace_points),
        "trace_point_count": len(trace_points),
        "read_path": "trace_max_fallback",
        "read_command": ":TRAC? TRACE1",
    }


def _acquire_average_value(
    inst: Any,
    *,
    post_init_settle_s: float = DEFAULT_POST_INIT_SETTLE_S,
) -> Dict[str, Any]:
    _trigger_single_sweep(inst, post_init_settle_s=post_init_settle_s)
    trace_points = _fetch_trace(inst)
    if not trace_points:
        raise RuntimeError("unable to compute PSD average from empty trace")
    return {
        "measured_value": sum(trace_points) / float(len(trace_points)),
        "trace_point_count": len(trace_points),
        "read_path": "trace_average",
        "read_command": ":TRAC? TRACE1",
    }


def _measure_psd_value_by_method(
    inst: Any,
    *,
    method: str,
    post_init_settle_s: float,
) -> Dict[str, Any]:
    normalized_method = normalize_psd_method(method) or PSD_METHOD_MARKER_PEAK
    if normalized_method == PSD_METHOD_MARKER_PEAK:
        return _acquire_marker_peak_value(inst, post_init_settle_s=post_init_settle_s)
    if normalized_method == PSD_METHOD_AVERAGE:
        return _acquire_average_value(inst, post_init_settle_s=post_init_settle_s)
    raise ValueError(f"unsupported PSD measurement method: {normalized_method}")


def measure_psd_keysight(
    source: Any,
    case: Any,
    *,
    timeout_ms: int = 5000,
    profile_settings: Dict[str, Any] | None = None,
    screenshot_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    detection = detect_keysight_xseries_analyzer(source)
    if not detection.get("usable"):
        raise RuntimeError(f"Keysight analyzer unavailable: {detection.get('reason', 'unknown')}")

    inst = detection["target"]
    cfg, instrument_cfg = _build_runtime_config(case, profile_settings=profile_settings)
    policy_ctx = _resolve_policy_context(case)
    mode_settle_s = _settle_seconds_from_cfg(instrument_cfg, "mode_settle_s", DEFAULT_MODE_SETTLE_S)
    post_config_settle_s = _settle_seconds_from_cfg(
        instrument_cfg,
        "post_config_settle_s",
        DEFAULT_POST_CONFIG_SETTLE_S,
    )
    post_init_settle_s = _settle_seconds_from_cfg(
        instrument_cfg,
        "post_init_settle_s",
        DEFAULT_POST_INIT_SETTLE_S,
    )

    log.info(
        "keysight psd measurement start | timeout_ms=%s ruleset_id=%s band=%s device_class=%s profile_name=%s profile_source=%s policy_source=%s psd_method=%s scpi_power_unit=%s display_unit=%s limit_value=%s limit_unit=%s canonical_limit=%s canonical_unit=%s cf_mhz=%s span_mhz=%s span_source=%s rbw_hz=%s vbw_hz=%s detector=%s trace_mode=%s average_enabled=%s avg_count=%s sweep_time_s=%s atten_db=%s ref_level_dbm=%s channel=%s case=%s target_class=%s",
        timeout_ms,
        policy_ctx["ruleset_id"],
        policy_ctx["band"],
        policy_ctx["device_class"],
        instrument_cfg.get("profile_name", ""),
        instrument_cfg.get("profile_source", ""),
        policy_ctx["policy_source"],
        policy_ctx["method"],
        policy_ctx["scpi_power_unit"],
        policy_ctx["display_unit"],
        policy_ctx["ruleset_limit_value"],
        policy_ctx["ruleset_limit_unit"],
        policy_ctx["canonical_limit_value"],
        PSD_CANONICAL_UNIT,
        _hz_to_mhz(cfg.center_freq_hz),
        _hz_to_mhz(cfg.span_hz),
        instrument_cfg.get("resolved_span_source", ""),
        cfg.rbw_hz,
        cfg.vbw_hz,
        cfg.detector,
        cfg.trace_mode,
        cfg.average_enabled,
        cfg.avg_count,
        cfg.sweep_time_s,
        cfg.atten_db,
        cfg.ref_level_dbm,
        getattr(case, "channel", ""),
        getattr(case, "key", ""),
        type(inst).__name__,
    )

    with _temporary_timeout(inst, timeout_ms):
        _configure_psd_measurement(
            inst,
            cfg,
            scpi_power_unit=policy_ctx["scpi_power_unit"],
            mode_settle_s=mode_settle_s,
            post_config_settle_s=post_config_settle_s,
        )
        acquisition = _measure_psd_value_by_method(
            inst,
            method=policy_ctx["method"],
            post_init_settle_s=post_init_settle_s,
        )

    measured = float(acquisition["measured_value"])
    canonical_measured = convert_psd_value(
        measured,
        from_unit=policy_ctx["display_unit"],
        to_unit=PSD_CANONICAL_UNIT,
    )
    stored_limit_value = convert_psd_value(
        policy_ctx["canonical_limit_value"],
        from_unit=PSD_CANONICAL_UNIT,
        to_unit=policy_ctx["display_unit"],
    )
    margin = round(policy_ctx["canonical_limit_value"] - canonical_measured, 6)
    verdict = "PASS" if margin >= 0 else "FAIL"
    display_payload = build_psd_display_payload(
        canonical_value_dbm_per_mhz=canonical_measured,
        display_unit=policy_ctx["display_unit"],
    )
    display_limit_payload = build_psd_display_payload(
        canonical_value_dbm_per_mhz=policy_ctx["canonical_limit_value"],
        display_unit=display_payload["display_unit"],
    )
    screenshot = capture_analyzer_screenshot_best_effort(
        source,
        run_id=str((screenshot_context or {}).get("run_id", "") or ""),
        result_id=str((screenshot_context or {}).get("result_id", "") or ""),
        case=case,
        requested_root_dir=str((screenshot_context or {}).get("screenshot_root_dir", "") or ""),
        settle_ms=(screenshot_context or {}).get("screenshot_settle_ms", 300),
    )
    log.info(
        "keysight psd result canonicalized | case=%s channel=%s method=%s read_path=%s raw_value=%s raw_unit=%s measured_dbm_per_mhz=%s limit_dbm_per_mhz=%s stored_limit_value=%s margin_db=%s display_value=%s display_limit=%s display_unit=%s canonical_unit=%s",
        getattr(case, "key", ""),
        getattr(case, "channel", ""),
        policy_ctx["method"],
        acquisition.get("read_path", ""),
        measured,
        policy_ctx["display_unit_label"],
        canonical_measured,
        policy_ctx["canonical_limit_value"],
        stored_limit_value,
        margin,
        display_payload["display_value"],
        display_limit_payload["display_value"],
        display_payload["display_unit"],
        display_payload["canonical_unit"],
    )
    return {
        "measured_value": measured,
        "limit_value": stored_limit_value,
        "margin_db": margin,
        "measurement_unit": policy_ctx["display_unit_label"],
        "canonical_measurement_unit": _psd_unit_label(PSD_CANONICAL_UNIT),
        "canonical_measured_value": canonical_measured,
        "canonical_limit_value": policy_ctx["canonical_limit_value"],
        "psd_result_unit": display_payload["display_unit"],
        "psd_canonical_unit": display_payload["canonical_unit"],
        "psd_method": policy_ctx["method"],
        "psd_limit_value": policy_ctx["ruleset_limit_value"],
        "psd_limit_unit": policy_ctx["ruleset_limit_unit"],
        "psd_limit_label": policy_ctx["ruleset_limit_label"],
        "psd_unit_policy_source": policy_ctx["policy_source"],
        "display_measured_value": display_payload["display_value"],
        "display_limit_value": display_limit_payload["display_value"],
        "display_measurement_unit": policy_ctx["display_unit_label"],
        "measurement_source": "keysight_xseries_scpi",
        "backend_reason": detection.get("reason", "idn_match"),
        "backend_idn": detection.get("idn", ""),
        "measurement_profile_name": instrument_cfg.get("profile_name", ""),
        "measurement_profile_source": instrument_cfg.get("profile_source", ""),
        "measurement_profile_test_type": instrument_cfg.get("test_type", ""),
        "measurement_profile_span_source": instrument_cfg.get("resolved_span_source", ""),
        "measurement_profile_resolved_span_source": instrument_cfg.get("resolved_profile_span_source", ""),
        "measurement_profile_default_span_hz": instrument_cfg.get("resolved_default_span_hz"),
        "scpi_trace_mode": cfg.trace_mode,
        "scpi_detector": cfg.detector,
        "scpi_average_enabled": bool(cfg.average_enabled),
        "scpi_avg_count": int(cfg.avg_count),
        "scpi_power_unit": policy_ctx["scpi_power_unit"],
        "scpi_span_hz": float(cfg.span_hz),
        "scpi_rbw_hz": float(cfg.rbw_hz),
        "scpi_vbw_hz": float(cfg.vbw_hz),
        "scpi_measurement_method": policy_ctx["method"],
        "scpi_read_path": acquisition.get("read_path", ""),
        "scpi_read_command": acquisition.get("read_command", ""),
        "ruleset_id": policy_ctx["ruleset_id"],
        "device_class": policy_ctx["device_class"],
        "trace_point_count": acquisition.get("trace_point_count", 0),
        "verdict": verdict,
        **screenshot,
    }
