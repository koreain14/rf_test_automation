from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, Iterator, Tuple

from application.analyzer_screenshot import capture_analyzer_screenshot_best_effort
from application.measurement_profile_runtime import build_consumable_measurement_profile
from application.measurements.keysight_obw_helper import detect_keysight_xseries_analyzer


log = logging.getLogger(__name__)


@dataclass
class KeysightTxpConfig:
    center_freq_hz: float
    integration_bw_hz: float
    span_hz: float
    rbw_hz: float
    vbw_hz: float
    detector: str = "RMS"
    trace_mode: str = "CLEAR_WRITE"
    sweep_time_s: float = 0.1
    rbw_auto: bool = False
    vbw_auto: bool = False
    sweep_auto: bool = False
    average_enabled: bool = False
    avg_count: int = 1
    atten_db: float = 10.0
    ref_level_dbm: float = 10.0
    sweep_points: int = 1001


DEFAULT_SPAN_HZ_MIN = 100_000_000.0
DEFAULT_RBW_HZ_MIN = 10_000.0
DEFAULT_RBW_HZ_MAX = 3_000_000.0
DEFAULT_SWEEP_TIME_S = 0.1
DEFAULT_AVG_COUNT = 1
DEFAULT_ATTEN_DB = 10.0
DEFAULT_REF_LEVEL_DBM = 10.0
DEFAULT_SWEEP_POINTS = 1001
DEFAULT_POLL_INTERVAL_S = 0.1
DEFAULT_MAX_WAIT_S = 60.0
DEFAULT_FETCH_POLL_TIMEOUT_MS = 500
DEFAULT_MODE_SETTLE_S = 0.05
DEFAULT_POST_CONFIG_SETTLE_S = 0.02
DEFAULT_POST_INIT_SETTLE_S = 0.2
DEFAULT_TXP_LIMIT_DBM = 30.0


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


def _read_system_error_best_effort(inst: Any) -> str:
    try:
        return str(inst.query("SYST:ERR?") or "").strip()
    except Exception:
        return ""


def _safe_write(inst: Any, cmd: str) -> None:
    try:
        inst.write(cmd)
    except Exception:
        system_error = _read_system_error_best_effort(inst)
        log.exception("keysight txp SCPI write failed | cmd=%s system_error=%s", cmd, system_error)
        raise


def _safe_query(inst: Any, cmd: str) -> str:
    try:
        return str(inst.query(cmd) or "").strip()
    except Exception:
        system_error = _read_system_error_best_effort(inst)
        log.exception("keysight txp SCPI query failed | cmd=%s system_error=%s", cmd, system_error)
        raise


def _quiet_query(inst: Any, cmd: str) -> str:
    return str(inst.query(cmd) or "").strip()


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


def _resolve_span_multiplier(cfg: Dict[str, Any]) -> float | None:
    span_mode = str(cfg.get("span_mode") or "").strip().upper()
    if span_mode == "BW_X2":
        return 2.0
    if cfg.get("span_multiplier") not in (None, ""):
        return _as_float(cfg.get("span_multiplier"), 0.0)
    return None


def _cfg_has_any(cfg: Dict[str, Any], *keys: str) -> bool:
    return any(cfg.get(key) not in (None, "") for key in keys)


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
    mode = str(value or "CLEAR_WRITE").strip().upper().replace(" ", "").replace("_", "").replace("/", "")
    aliases = {
        "MAXHOLD": "MAXH",
        "MAXH": "MAXH",
        "AVERAGE": "AVER",
        "AVER": "AVER",
        "WRITE": "WRIT",
        "WRIT": "WRIT",
        "CLEARWRITE": "WRIT",
    }
    return aliases.get(mode, "WRIT")


def _settle_seconds_from_cfg(cfg: Dict[str, Any], key: str, default: float) -> float:
    return max(0.0, _as_float(cfg.get(key), default))


def _resolve_txp_bandwidth_hz(
    cfg: Dict[str, Any],
    *,
    bw_mhz: float,
) -> float:
    default_hz = max(float(bw_mhz) * 1e6, 1.0)
    for hz_key, mhz_key in (
        ("integration_bw_hz", "integration_bw_mhz"),
        ("chp_bandwidth_hz", "chp_bandwidth_mhz"),
        ("bandwidth_hz", "bandwidth_mhz"),
    ):
        if cfg.get(hz_key) not in (None, "") or cfg.get(mhz_key) not in (None, ""):
            return _resolve_hz(cfg, hz_key=hz_key, mhz_key=mhz_key, default_hz=default_hz)
    return float(default_hz)


def _resolve_txp_span_hz(
    cfg: Dict[str, Any],
    *,
    bw_mhz: float,
    measurement_field_sources: Dict[str, Any],
) -> tuple[float, float, str, str]:
    default_span_hz = max(bw_mhz * 2.0 * 1.0e6, DEFAULT_SPAN_HZ_MIN)
    profile_span_source = str(
        measurement_field_sources.get("span_hz")
        or measurement_field_sources.get("span_mhz")
        or ""
    ).strip()
    if profile_span_source == "profile_override":
        return (
            _resolve_hz(cfg, hz_key="span_hz", mhz_key="span_mhz", default_hz=default_span_hz),
            default_span_hz,
            profile_span_source,
            "profile_override",
        )

    span_multiplier = _resolve_span_multiplier(cfg)
    if span_multiplier not in (None, 0.0):
        span_min_hz = _as_float(cfg.get("span_min_hz"), DEFAULT_SPAN_HZ_MIN)
        computed_span_hz = max(bw_mhz * float(span_multiplier) * 1.0e6, span_min_hz)
        return (
            computed_span_hz,
            default_span_hz,
            "profile_policy",
            "profile_policy_bw_multiplier",
        )

    return (
        float(default_span_hz),
        default_span_hz,
        profile_span_source or "none",
        "computed_default",
    )


def _txp_average_enabled(instrument_cfg: Dict[str, Any], cfg: KeysightTxpConfig) -> bool:
    for key in ("average_enabled", "txp_average_enabled", "average", "txp_average"):
        if instrument_cfg.get(key) not in (None, ""):
            return _as_bool(instrument_cfg.get(key), True)
    return bool(cfg.average_enabled or int(cfg.avg_count or 0) > 1)


def _build_runtime_config(case: Any, profile_settings: Dict[str, Any] | None = None) -> tuple[KeysightTxpConfig, Dict[str, Any]]:
    center_freq_mhz = _as_float(getattr(case, "center_freq_mhz", 0.0), 0.0)
    bw_mhz = _as_float(getattr(case, "bw_mhz", 20.0), 20.0)
    instrument_cfg = build_consumable_measurement_profile(
        test_type=getattr(case, "test_type", ""),
        resolved_profile=dict(profile_settings or {}),
        instrument_snapshot=dict(getattr(case, "instrument", {}) or {}),
    )
    measurement_field_sources = dict(instrument_cfg.get("measurement_field_sources") or {})
    span_hz, default_span_hz, resolved_profile_span_source, applied_span_source = _resolve_txp_span_hz(
        instrument_cfg,
        bw_mhz=bw_mhz,
        measurement_field_sources=measurement_field_sources,
    )
    integration_bw_hz = _resolve_txp_bandwidth_hz(instrument_cfg, bw_mhz=bw_mhz)
    rbw_hz = _resolve_hz(
        instrument_cfg,
        hz_key="rbw_hz",
        mhz_key="rbw_mhz",
        default_hz=max(min(integration_bw_hz / 20.0, DEFAULT_RBW_HZ_MAX), DEFAULT_RBW_HZ_MIN),
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
    average_enabled_default = _as_int(instrument_cfg.get("avg_count"), DEFAULT_AVG_COUNT) > 1

    raw_detector = instrument_cfg.get("detector", "RMS")
    raw_trace_mode = instrument_cfg.get("trace_mode", "CLEAR_WRITE")
    normalized_detector = _normalize_detector(raw_detector)
    normalized_trace_mode = _normalize_trace_mode(raw_trace_mode)
    instrument_cfg = dict(instrument_cfg)
    instrument_cfg["resolved_profile_span_source"] = resolved_profile_span_source
    instrument_cfg["resolved_span_source"] = applied_span_source
    instrument_cfg["resolved_span_hz"] = span_hz
    instrument_cfg["resolved_default_span_hz"] = default_span_hz
    instrument_cfg["resolved_integration_bw_hz"] = integration_bw_hz

    log.info(
        "keysight txp profile normalization | case=%s test_type=%s profile_name=%s profile_source=%s raw_trace_mode=%s normalized_trace_mode=%s raw_detector=%s normalized_detector=%s average_enabled_default=%s avg_count=%s integration_bw_hz=%s profile_span_source=%s applied_span_source=%s bw_mhz=%s span_hz=%s default_span_hz=%s rbw_hz=%s vbw_hz=%s",
        getattr(case, "key", ""),
        getattr(case, "test_type", ""),
        instrument_cfg.get("profile_name", ""),
        instrument_cfg.get("profile_source", ""),
        raw_trace_mode,
        normalized_trace_mode,
        raw_detector,
        normalized_detector,
        average_enabled_default,
        _as_int(instrument_cfg.get("avg_count"), DEFAULT_AVG_COUNT),
        integration_bw_hz,
        resolved_profile_span_source,
        applied_span_source,
        bw_mhz,
        span_hz,
        default_span_hz,
        rbw_hz,
        vbw_hz,
    )

    return (
        KeysightTxpConfig(
            center_freq_hz=center_freq_mhz * 1e6,
            integration_bw_hz=integration_bw_hz,
            span_hz=span_hz,
            rbw_hz=rbw_hz,
            vbw_hz=vbw_hz,
            detector=normalized_detector,
            trace_mode=normalized_trace_mode,
            sweep_time_s=_as_float(instrument_cfg.get("sweep_time_s"), DEFAULT_SWEEP_TIME_S),
            rbw_auto=_as_bool(instrument_cfg.get("rbw_auto"), rbw_auto_default),
            vbw_auto=_as_bool(instrument_cfg.get("vbw_auto"), vbw_auto_default),
            sweep_auto=_as_bool(instrument_cfg.get("sweep_auto"), sweep_auto_default),
            average_enabled=_as_bool(instrument_cfg.get("average_enabled"), average_enabled_default),
            avg_count=max(1, _as_int(instrument_cfg.get("avg_count"), DEFAULT_AVG_COUNT)),
            atten_db=_as_float(
                instrument_cfg.get("atten_db", instrument_cfg.get("att_db")),
                DEFAULT_ATTEN_DB,
            ),
            ref_level_dbm=_as_float(instrument_cfg.get("ref_level_dbm"), DEFAULT_REF_LEVEL_DBM),
            sweep_points=max(101, _as_int(instrument_cfg.get("sweep_points"), DEFAULT_SWEEP_POINTS)),
        ),
        instrument_cfg,
    )


def _resolve_limit_context(case: Any, instrument_cfg: Dict[str, Any]) -> Dict[str, Any]:
    tags = dict(getattr(case, "tags", {}) or {})
    raw_limit_value = (
        tags.get("txp_limit_value")
        if tags.get("txp_limit_value") not in (None, "")
        else tags.get("limit_value")
    )
    if raw_limit_value in (None, ""):
        raw_limit_value = instrument_cfg.get("limit_value")
    try:
        limit_value = float(raw_limit_value) if raw_limit_value not in (None, "") else DEFAULT_TXP_LIMIT_DBM
    except Exception:
        limit_value = DEFAULT_TXP_LIMIT_DBM
    comparator = str(tags.get("txp_comparator") or tags.get("comparator") or "upper_limit").strip() or "upper_limit"
    return {
        "ruleset_id": str(tags.get("ruleset_id", "") or ""),
        "band": str(getattr(case, "band", "") or tags.get("band", "") or ""),
        "device_class": str(tags.get("device_class", "") or ""),
        "measurement_profile_name": str(tags.get("measurement_profile_name", "") or ""),
        "limit_value": float(limit_value),
        "limit_unit": "dBm",
        "comparator": comparator,
        "limit_source": "case_tag"
        if tags.get("txp_limit_value") not in (None, "") or tags.get("limit_value") not in (None, "")
        else ("profile_override" if instrument_cfg.get("limit_value") not in (None, "") else "default_fallback"),
    }


def _mock_from_case(case: Any) -> Dict[str, Any]:
    instrument_cfg = build_consumable_measurement_profile(
        test_type=getattr(case, "test_type", ""),
        resolved_profile=dict(getattr(case, "instrument", {}) or {}),
        instrument_snapshot=dict(getattr(case, "instrument", {}) or {}),
    )
    limit_ctx = _resolve_limit_context(case, instrument_cfg)
    measured = round(min(limit_ctx["limit_value"] - 1.0, 17.0), 6)
    difference_value = round(measured - limit_ctx["limit_value"], 6)
    margin = round(limit_ctx["limit_value"] - measured, 6)
    verdict = "PASS" if margin >= 0 else "FAIL"
    return {
        "measured_value": measured,
        "raw_measured_value": measured,
        "limit_value": limit_ctx["limit_value"],
        "margin_db": margin,
        "measurement_unit": "dBm",
        "measurement_source": "mock",
        "backend_reason": "mock_fallback",
        "difference_value": difference_value,
        "difference_unit": "dBm",
        "comparator": limit_ctx["comparator"],
        "verdict": verdict,
    }


def _mock_from_config(cfg: KeysightTxpConfig) -> Tuple[float, Dict[str, Any]]:
    measured = round(min(float(cfg.ref_level_dbm) - 3.0, 17.0), 6)
    raw = {
        "method": "mock_keysight",
        "center_freq_hz": float(cfg.center_freq_hz),
        "integration_bw_hz": float(cfg.integration_bw_hz),
        "span_hz": float(cfg.span_hz),
        "rbw_hz": float(cfg.rbw_hz),
        "vbw_hz": float(cfg.vbw_hz),
        "rbw_auto": bool(cfg.rbw_auto),
        "vbw_auto": bool(cfg.vbw_auto),
        "sweep_auto": bool(cfg.sweep_auto),
        "sweep_time_s": float(cfg.sweep_time_s),
        "average_enabled": bool(cfg.average_enabled),
        "avg_count": int(cfg.avg_count),
        "atten_db": float(cfg.atten_db),
        "ref_level_dbm": float(cfg.ref_level_dbm),
        "detector": str(cfg.detector),
        "trace_mode": str(cfg.trace_mode),
        "sweep_points": int(cfg.sweep_points),
    }
    return measured, raw


def mock_txp_measurement(obj: Any):
    """
    Compatibility helper.

    - procedures.py passes a case-like object and expects a dict result.
    - helper tests or future preview flows may pass KeysightTxpConfig and expect (measured_dbm, raw_dict).
    """
    if isinstance(obj, KeysightTxpConfig):
        return _mock_from_config(obj)
    return _mock_from_case(obj)


def _write_stage(inst: Any, stage: str, cmd: str) -> None:
    log.info("keysight txp SCPI write | stage=%s cmd=%s", stage, cmd)
    _safe_write(inst, cmd)


def _query_stage(inst: Any, stage: str, cmd: str) -> str:
    log.info("keysight txp SCPI query | stage=%s cmd=%s", stage, cmd)
    return _safe_query(inst, cmd)


def _best_effort_query_candidates(inst: Any, *, stage: str, commands: Tuple[str, ...]) -> Tuple[str, str]:
    last_error = ""
    for cmd in commands:
        try:
            response = _query_stage(inst, stage, cmd)
            return cmd, response
        except Exception as exc:
            last_error = str(exc)
            log.info(
                "keysight txp SCPI readback candidate failed | stage=%s cmd=%s err=%s",
                stage,
                cmd,
                exc,
            )
    return "", last_error


def _sync_stage(inst: Any, stage: str, *, fallback_sleep_s: float = 0.0) -> None:
    try:
        response = _query_stage(inst, f"{stage}_opc", "*OPC?")
        log.info("keysight txp SCPI sync | stage=%s opc=%s", stage, response)
        return
    except Exception as exc:
        log.info(
            "keysight txp SCPI sync fallback | stage=%s fallback_sleep_s=%s err=%s",
            stage,
            fallback_sleep_s,
            exc,
        )
    if fallback_sleep_s > 0.0:
        time.sleep(float(fallback_sleep_s))


def _log_txp_apply_readback(inst: Any) -> None:
    trace_cmd, trace_response = _best_effort_query_candidates(
        inst,
        stage="trace_readback",
        commands=(
            ":TRAC1:CHP:TYPE?",
            ":TRAC:CHP:TYPE?",
        ),
    )
    detector_cmd, detector_response = _best_effort_query_candidates(
        inst,
        stage="detector_readback",
        commands=(
            ":CHP:DET?",
            ":DET?",
        ),
    )
    average_cmd, average_response = _best_effort_query_candidates(
        inst,
        stage="average_readback",
        commands=(
            ":CHP:AVER?",
            ":AVER?",
        ),
    )
    avg_count_cmd, avg_count_response = _best_effort_query_candidates(
        inst,
        stage="average_count_readback",
        commands=(
            ":CHP:AVER:COUN?",
            ":AVER:COUN?",
        ),
    )
    log.info(
        "keysight txp apply readback | trace_cmd=%s trace_response=%s detector_cmd=%s detector_response=%s average_cmd=%s average_response=%s avg_count_cmd=%s avg_count_response=%s",
        trace_cmd,
        trace_response,
        detector_cmd,
        detector_response,
        average_cmd,
        average_response,
        avg_count_cmd,
        avg_count_response,
    )


def _estimated_wait_seconds(cfg: KeysightTxpConfig, instrument_cfg: Dict[str, Any]) -> float:
    configured = instrument_cfg.get("measurement_wait_s")
    if configured not in (None, ""):
        return max(1.0, _as_float(configured, DEFAULT_MAX_WAIT_S))

    if cfg.sweep_auto:
        return max(10.0, float(cfg.avg_count) * 2.0)

    estimated = max(1.0, float(cfg.sweep_time_s)) * max(1.0, float(cfg.avg_count))
    return max(3.0, min(max(estimated * 3.0, 3.0), DEFAULT_MAX_WAIT_S))


def _estimated_fetch_poll_timeout_ms(instrument_cfg: Dict[str, Any], request_timeout_ms: int) -> int:
    configured = instrument_cfg.get("fetch_poll_timeout_ms")
    if configured not in (None, ""):
        return max(100, _as_int(configured, DEFAULT_FETCH_POLL_TIMEOUT_MS))
    return max(100, min(int(request_timeout_ms or DEFAULT_FETCH_POLL_TIMEOUT_MS), DEFAULT_FETCH_POLL_TIMEOUT_MS))


def _configure_txp_measurement(
    inst: Any,
    cfg: KeysightTxpConfig,
    instrument_cfg: Dict[str, Any] | None = None,
    *,
    mode_settle_s: float = DEFAULT_MODE_SETTLE_S,
    post_config_settle_s: float = DEFAULT_POST_CONFIG_SETTLE_S,
) -> None:
    average_enabled = _txp_average_enabled(dict(instrument_cfg or {}), cfg)
    commands = [
        ("prepare", "*CLS"),
        ("prepare", ":INIT:CONT OFF"),
        ("prepare", ":ABOR"),
        ("mode", ":CONF:CHP"),
        ("average", f":CHP:AVER {_format_scpi_bool(average_enabled)}"),
        ("frequency", f":FREQ:CENT {_format_scpi_value(_hz_to_mhz(cfg.center_freq_hz))}MHZ"),
        ("bandwidth", f":CHP:BAND:INT {_format_scpi_value(_hz_to_mhz(cfg.integration_bw_hz))}MHZ"),
        ("span", f":CHP:FREQ:SPAN {_format_scpi_value(_hz_to_mhz(cfg.span_hz))}MHZ"),
        ("rbw", f":CHP:BAND:RES {_format_scpi_value(_hz_to_mhz(cfg.rbw_hz))}MHZ"),
        ("vbw", f":CHP:BAND:VID {_format_scpi_value(_hz_to_mhz(cfg.vbw_hz))}MHZ"),
        ("rbw_auto", f":CHP:BAND:RES:AUTO {_format_scpi_bool(cfg.rbw_auto)}"),
        ("vbw_auto", f":CHP:BAND:VID:AUTO {_format_scpi_bool(cfg.vbw_auto)}"),
        ("sweep", f":CHP:SWE:TIME {_format_scpi_value(cfg.sweep_time_s)}S"),
        ("sweep_auto", f":CHP:SWE:TIME:AUTO {_format_scpi_bool(cfg.sweep_auto)}"),
        ("unit", ":UNIT:POW DBM"),
        ("sweep_points", f":SWE:POIN {_as_int(cfg.sweep_points, DEFAULT_SWEEP_POINTS)}"),
        ("atten", f":POW:ATT {_format_scpi_value(cfg.atten_db)}DB"),
        ("display", f":DISP:CHP:VIEW:WIND:TRAC:Y:RLEV {_format_scpi_value(cfg.ref_level_dbm)}DBM"),
        ("trace", f":TRAC1:CHP:TYPE {cfg.trace_mode}"),
        ("detector", f":CHP:DET {cfg.detector}"),
    ]
    if average_enabled:
        commands.insert(5, ("average", f":CHP:AVER:COUN {_as_int(cfg.avg_count, DEFAULT_AVG_COUNT)}"))
    log.info(
        "keysight txp configure apply | trace_mode=%s detector=%s average_enabled=%s avg_count=%s integration_bw_hz=%s mode_settle_s=%s post_config_settle_s=%s",
        cfg.trace_mode,
        cfg.detector,
        average_enabled,
        cfg.avg_count,
        cfg.integration_bw_hz,
        mode_settle_s,
        post_config_settle_s,
    )
    for stage, cmd in commands:
        _write_stage(inst, stage, cmd)
        if stage == "trace":
            log.info(
                "keysight txp inter-command settle | after_stage=%s before_stage=%s sleep_s=1.0",
                "trace",
                "detector",
            )
            time.sleep(1.0)
        if cmd == ":ABOR":
            _sync_stage(inst, "post_abort", fallback_sleep_s=mode_settle_s)
        elif cmd == ":CONF:CHP":
            _sync_stage(inst, "post_conf_chp", fallback_sleep_s=mode_settle_s)
            log.info(
                "keysight txp inter-command settle | after_stage=%s before_stage=%s sleep_s=1.0",
                "mode",
                "average",
            )
            time.sleep(1.0)
    _sync_stage(inst, "post_txp_config", fallback_sleep_s=post_config_settle_s)
    _log_txp_apply_readback(inst)


def _parse_first_float(response: str) -> float:
    for token in str(response or "").replace("\n", ",").split(","):
        stripped = token.strip()
        if not stripped:
            continue
        try:
            return float(stripped)
        except Exception:
            continue
    raise ValueError(f"no float value found in response={response!r}")


def _fetch_txp_dbm(inst: Any) -> float:
    responses: list[str] = []
    for stage, cmd in (
        ("result_fetch", ":FETC:CHP?"),
        ("result_fetch_fallback", ":READ:CHP?"),
    ):
        try:
            log.info("keysight txp SCPI query | stage=%s cmd=%s", stage, cmd)
            response = _quiet_query(inst, cmd)
            responses.append(response)
            return _parse_first_float(response)
        except Exception as exc:
            log.info("keysight txp result query pending | stage=%s cmd=%s err=%s", stage, cmd, exc)
    raise RuntimeError(f"unable to read TXP result from analyzer | responses={responses}")


def _poll_txp_result_dbm(
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
                value = _fetch_txp_dbm(inst)
            log.info(
                "keysight txp result detected | max_wait_s=%s fetch_poll_timeout_ms=%s value_dbm=%s",
                max_wait_s,
                fetch_poll_timeout_ms,
                value,
            )
            return value
        except Exception as exc:
            last_fetch_error = str(exc)
            log.info(
                "keysight txp result not ready yet | max_wait_s=%s fetch_poll_timeout_ms=%s err=%s",
                max_wait_s,
                fetch_poll_timeout_ms,
                exc,
            )
        time.sleep(max(0.01, float(poll_interval_s)))

    raise RuntimeError(
        "TXP measurement did not complete before deadline | "
        f"max_wait_s={max_wait_s} fetch_poll_timeout_ms={fetch_poll_timeout_ms} "
        f"last_fetch_error={last_fetch_error}"
    )


def _acquire_txp_dbm(
    inst: Any,
    *,
    max_wait_s: float,
    fetch_poll_timeout_ms: int,
    post_init_settle_s: float = DEFAULT_POST_INIT_SETTLE_S,
) -> float:
    _write_stage(inst, "init", ":INIT:IMM")
    _sync_stage(inst, "post_init", fallback_sleep_s=post_init_settle_s)
    return _poll_txp_result_dbm(
        inst,
        max_wait_s=max_wait_s,
        fetch_poll_timeout_ms=fetch_poll_timeout_ms,
    )


def _clear_status_best_effort(inst: Any, *, stage: str) -> None:
    try:
        log.info("keysight txp SCPI clear status | stage=%s cmd=*CLS", stage)
        _safe_write(inst, "*CLS")
    except Exception as exc:
        log.info("keysight txp SCPI clear status skipped | stage=%s err=%s", stage, exc)


def measure_txp_keysight(
    source: Any,
    case: Any,
    *,
    timeout_ms: int = 5000,
    retries: int = 1,
    profile_settings: Dict[str, Any] | None = None,
    screenshot_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    detection = detect_keysight_xseries_analyzer(source)
    if not detection.get("usable"):
        raise RuntimeError(f"Keysight analyzer unavailable: {detection.get('reason', 'unknown')}")

    inst = detection["target"]
    cfg, instrument_cfg = _build_runtime_config(case, profile_settings=profile_settings)
    limit_ctx = _resolve_limit_context(case, instrument_cfg)
    max_wait_s = _estimated_wait_seconds(cfg, instrument_cfg)
    fetch_poll_timeout_ms = _estimated_fetch_poll_timeout_ms(instrument_cfg, timeout_ms)
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

    last_exc = None
    last_stage = "startup"
    for attempt in range(1, retries + 1):
        try:
            log.info(
                "keysight txp measurement start | attempt=%s/%s timeout_ms=%s max_wait_s=%s fetch_poll_timeout_ms=%s post_init_settle_s=%s ruleset_id=%s band=%s device_class=%s profile_name=%s profile_source=%s limit_value=%s limit_unit=%s limit_source=%s comparator=%s cf_mhz=%s integration_bw_mhz=%s span_mhz=%s rbw_auto=%s rbw_mhz=%s vbw_auto=%s vbw_mhz=%s sweep_auto=%s sweep_time_s=%s atten_db=%s ref_level_dbm=%s detector=%s avg_count=%s trace_mode=%s channel=%s case=%s target_class=%s",
                attempt,
                retries,
                timeout_ms,
                max_wait_s,
                fetch_poll_timeout_ms,
                post_init_settle_s,
                limit_ctx["ruleset_id"],
                limit_ctx["band"],
                limit_ctx["device_class"],
                instrument_cfg.get("profile_name", ""),
                instrument_cfg.get("profile_source", ""),
                limit_ctx["limit_value"],
                limit_ctx["limit_unit"],
                limit_ctx["limit_source"],
                limit_ctx["comparator"],
                _hz_to_mhz(cfg.center_freq_hz),
                _hz_to_mhz(cfg.integration_bw_hz),
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
                getattr(case, "channel", ""),
                getattr(case, "key", ""),
                type(inst).__name__,
            )
            with _temporary_timeout(inst, timeout_ms):
                last_stage = "configure"
                _configure_txp_measurement(
                    inst,
                    cfg,
                    instrument_cfg=instrument_cfg,
                    mode_settle_s=mode_settle_s,
                    post_config_settle_s=post_config_settle_s,
                )
                last_stage = "acquire"
                measured_dbm = _acquire_txp_dbm(
                    inst,
                    max_wait_s=max_wait_s,
                    fetch_poll_timeout_ms=fetch_poll_timeout_ms,
                    post_init_settle_s=post_init_settle_s,
                )

            difference_value = round(measured_dbm - limit_ctx["limit_value"], 6)
            margin = round(limit_ctx["limit_value"] - measured_dbm, 6)
            verdict = "PASS" if margin >= 0 else "FAIL"
            _clear_status_best_effort(inst, stage="pre_screenshot")
            screenshot = capture_analyzer_screenshot_best_effort(
                source,
                run_id=str((screenshot_context or {}).get("run_id", "") or ""),
                result_id=str((screenshot_context or {}).get("result_id", "") or ""),
                case=case,
                requested_root_dir=str((screenshot_context or {}).get("screenshot_root_dir", "") or ""),
                settle_ms=(screenshot_context or {}).get("screenshot_settle_ms", 300),
            )
            return {
                "measured_value": measured_dbm,
                "raw_measured_value": measured_dbm,
                "limit_value": limit_ctx["limit_value"],
                "margin_db": margin,
                "measurement_unit": "dBm",
                "measurement_source": "keysight_xseries_scpi",
                "backend_reason": detection.get("reason", "idn_match"),
                "backend_idn": detection.get("idn", ""),
                "measurement_profile_name": instrument_cfg.get("profile_name", ""),
                "measurement_profile_source": instrument_cfg.get("profile_source", ""),
                "measurement_profile_test_type": instrument_cfg.get("test_type", ""),
                "measurement_profile_span_source": instrument_cfg.get("resolved_span_source", ""),
                "measurement_profile_resolved_span_source": instrument_cfg.get("resolved_profile_span_source", ""),
                "measurement_profile_default_span_hz": instrument_cfg.get("resolved_default_span_hz"),
                "difference_value": difference_value,
                "difference_unit": "dBm",
                "comparator": limit_ctx["comparator"],
                "scpi_timeout_ms": int(timeout_ms),
                "scpi_max_wait_s": float(max_wait_s),
                "scpi_fetch_poll_timeout_ms": int(fetch_poll_timeout_ms),
                "scpi_trace_mode": cfg.trace_mode,
                "scpi_detector": cfg.detector,
                "scpi_average_enabled": bool(_txp_average_enabled(instrument_cfg, cfg)),
                "scpi_avg_count": int(cfg.avg_count),
                "scpi_rbw_auto": bool(cfg.rbw_auto),
                "scpi_vbw_auto": bool(cfg.vbw_auto),
                "scpi_sweep_auto": bool(cfg.sweep_auto),
                "scpi_span_hz": float(cfg.span_hz),
                "scpi_rbw_hz": float(cfg.rbw_hz),
                "scpi_vbw_hz": float(cfg.vbw_hz),
                "scpi_integration_bw_hz": float(cfg.integration_bw_hz),
                "scpi_measurement_method": "CHP",
                "ruleset_id": limit_ctx["ruleset_id"],
                "device_class": limit_ctx["device_class"],
                "verdict": verdict,
                **screenshot,
            }
        except Exception as exc:
            last_exc = exc
            log.warning(
                "keysight txp measurement failed | attempt=%s/%s stage=%s timeout_ms=%s err=%s",
                attempt,
                retries,
                last_stage,
                timeout_ms,
                exc,
            )

    raise RuntimeError(f"Keysight TXP SCPI measurement failed at stage={last_stage}: {last_exc}")


__all__ = [
    "KeysightTxpConfig",
    "measure_txp_keysight",
    "mock_txp_measurement",
]
