from __future__ import annotations

import logging
import os
from pathlib import Path
import time
from typing import Any, Iterator


log = logging.getLogger(__name__)


DEFAULT_SCREENSHOT_ROOT = Path("artifacts") / "runs"
DEFAULT_SCREENSHOT_EXTENSION = ".png"
DEFAULT_INSTRUMENT_SCREENSHOT_DIR = "C:\\SCREENSHOT"
DEFAULT_SCREENSHOT_SETTLE_MS = 300
DEFAULT_POST_STORE_SETTLE_MS = 150
DEFAULT_PRESET_DIR_NAME = "preset"
DEFAULT_BAND_DIR_NAME = "band"
DEFAULT_VOLTAGE_TOKEN = "voltage"
DEFAULT_CHANNEL_TOKEN = "ch"
DEFAULT_BW_TOKEN = "bw"


def capture_analyzer_screenshot_best_effort(
    source: Any,
    *,
    run_id: str,
    result_id: str,
    case: Any,
    requested_root_dir: str = "",
    settle_ms: int | float = DEFAULT_SCREENSHOT_SETTLE_MS,
) -> dict[str, Any]:
    metadata = _build_base_metadata(
        run_id=run_id,
        result_id=result_id,
        case=case,
        requested_root_dir=requested_root_dir,
    )
    if not run_id or not result_id:
        metadata.update(
            {
                "screenshot_capture_status": "skipped_missing_context",
                "screenshot_capture_error": "run_id/result_id is required for screenshot capture",
            }
        )
        return metadata

    session = _unwrap_binary_capable_session(source)
    if session is None:
        metadata.update(
            {
                "screenshot_capture_status": "skipped_unsupported",
                "screenshot_capture_error": "no binary-capable SCPI session found",
            }
        )
        return metadata

    idn = _query_idn_best_effort(source, session)
    strategy = _resolve_strategy(idn=idn, source=source)
    metadata["screenshot_strategy"] = strategy["name"]
    metadata["screenshot_backend_idn"] = idn
    metadata["screenshot_settle_ms"] = int(_coerce_settle_ms(settle_ms))

    path_info = _resolve_output_path(
        requested_root_dir=requested_root_dir,
        run_id=run_id,
        case=case,
        result_id=result_id,
    )
    metadata.update(path_info["metadata"])

    output_path = path_info.get("path")
    if output_path is None:
        metadata.update(
            {
                "screenshot_capture_status": "path_resolve_failed",
                "screenshot_capture_error": path_info["metadata"].get("screenshot_capture_error", ""),
            }
        )
        return metadata

    try:
        _settle_before_capture(session, settle_ms=settle_ms)
        payload = _capture_payload(session, strategy)
        output_path.write_bytes(payload)
        metadata.update(
            {
                "screenshot_capture_status": "captured",
                "screenshot_capture_error": "",
                "screenshot_size_bytes": int(len(payload)),
            }
        )
        log.info(
            "analyzer screenshot captured | run_id=%s result_id=%s case=%s strategy=%s requested_root=%s final_path=%s stored_path=%s fallback=%s size_bytes=%s",
            run_id,
            result_id,
            getattr(case, "key", ""),
            strategy["name"],
            requested_root_dir,
            str(output_path),
            metadata.get("screenshot_path", ""),
            metadata.get("screenshot_fallback_used", False),
            metadata.get("screenshot_size_bytes", 0),
        )
    except Exception as exc:
        metadata.update(
            {
                "screenshot_capture_status": "capture_failed",
                "screenshot_capture_error": str(exc),
            }
        )
        log.warning(
            "analyzer screenshot capture failed | run_id=%s result_id=%s case=%s strategy=%s final_path=%s err=%s",
            run_id,
            result_id,
            getattr(case, "key", ""),
            strategy["name"],
            str(output_path),
            exc,
        )
    return metadata


def _build_base_metadata(
    *,
    run_id: str,
    result_id: str,
    case: Any,
    requested_root_dir: str,
) -> dict[str, Any]:
    return {
        "screenshot_capture_status": "",
        "screenshot_capture_error": "",
        "screenshot_path": "",
        "screenshot_abs_path": "",
        "screenshot_root_dir": "",
        "screenshot_requested_root_dir": str(requested_root_dir or "").strip(),
        "screenshot_storage_mode": "",
        "screenshot_fallback_used": False,
        "screenshot_strategy": "",
        "screenshot_backend_idn": "",
        "screenshot_file_name": "",
        "screenshot_size_bytes": 0,
        "screenshot_settle_ms": DEFAULT_SCREENSHOT_SETTLE_MS,
        "screenshot_run_id": str(run_id or ""),
        "screenshot_result_id": str(result_id or ""),
        "screenshot_case_key": str(getattr(case, "key", "") or ""),
    }


def _iter_targets(obj: Any) -> Iterator[Any]:
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


def _unwrap_binary_capable_session(source: Any) -> Any | None:
    for target in _iter_targets(source):
        if hasattr(target, "query_binary_values"):
            return target
        if hasattr(target, "write") and hasattr(target, "read_raw"):
            return target
    return None


def _query_idn_best_effort(source: Any, session: Any) -> str:
    for target in _iter_targets(source):
        if hasattr(target, "query_idn"):
            try:
                return str(target.query_idn() or "").strip()
            except Exception:
                pass
    try:
        if hasattr(session, "query"):
            return str(session.query("*IDN?") or "").strip()
    except Exception:
        pass
    return ""


def _resolve_strategy(*, idn: str, source: Any) -> dict[str, Any]:
    blob = f"{type(source).__name__} {idn}".lower()
    if any(token in blob for token in ("rohde", "schwarz", "fsw", "esw")):
        return {
            "name": "rohde_schwarz",
            "prep_commands": (
                "HCOP:DEV:LANG PNG",
            ),
            "query_commands": (
                "HCOP:DATA?",
                "HCOP:SDUM:DATA?",
            ),
        }
    return {
        "name": "keysight_xseries",
        "prep_commands": (),
        "query_commands": (),
    }


def _resolve_output_path(
    *,
    requested_root_dir: str,
    run_id: str,
    case: Any,
    result_id: str,
) -> dict[str, Any]:
    workspace_root = Path.cwd()
    default_root = (workspace_root / DEFAULT_SCREENSHOT_ROOT).resolve()
    requested_root = _resolve_requested_root(requested_root_dir, workspace_root)
    relative_run_path = _build_relative_run_path(run_id=run_id, case=case)
    file_name = _build_file_name(case=case, result_id=result_id)

    metadata: dict[str, Any] = {
        "screenshot_requested_root_dir": str(requested_root) if requested_root else str(requested_root_dir or "").strip(),
        "screenshot_file_name": file_name,
    }

    if requested_root is not None:
        try:
            target_dir = requested_root / relative_run_path
            target_dir.mkdir(parents=True, exist_ok=True)
            final_path = target_dir / file_name
            metadata.update(
                _build_path_metadata(
                    final_path=final_path,
                    root_dir=requested_root,
                    workspace_root=workspace_root,
                    storage_mode="custom_root",
                    fallback_used=False,
                )
            )
            return {"path": final_path, "metadata": metadata}
        except Exception as exc:
            log.warning(
                "screenshot custom root fallback | requested_root=%s run_id=%s err=%s",
                requested_root,
                run_id,
                exc,
            )
            metadata["screenshot_capture_error"] = str(exc)

    try:
        target_dir = default_root / relative_run_path
        target_dir.mkdir(parents=True, exist_ok=True)
        final_path = target_dir / file_name
        metadata.update(
            _build_path_metadata(
                final_path=final_path,
                root_dir=default_root,
                workspace_root=workspace_root,
                storage_mode="default_root",
                fallback_used=requested_root is not None,
            )
        )
        return {"path": final_path, "metadata": metadata}
    except Exception as exc:
        metadata.update(
            {
                "screenshot_capture_error": str(exc),
                "screenshot_capture_status": "path_resolve_failed",
            }
        )
        return {"path": None, "metadata": metadata}


def _resolve_requested_root(requested_root_dir: str, workspace_root: Path) -> Path | None:
    text = str(requested_root_dir or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = workspace_root / path
    return path.resolve()


def _build_relative_run_path(*, run_id: str, case: Any) -> Path:
    preset_dir = _resolve_preset_dir_name(case)
    band_dir = _resolve_band_dir_name(case)
    safe_run_id = _slug(str(run_id or "")) or "run"
    return Path(preset_dir) / safe_run_id / band_dir


def _resolve_preset_dir_name(case: Any) -> str:
    tags = _case_tags(case)
    preset_value = (
        tags.get("preset")
        or tags.get("preset_name")
        or tags.get("preset_id")
        or DEFAULT_PRESET_DIR_NAME
    )
    return _slug(str(preset_value or "")) or DEFAULT_PRESET_DIR_NAME


def _resolve_band_dir_name(case: Any) -> str:
    band_value = getattr(case, "band", "")
    safe_band = _slug(str(band_value or ""))
    return safe_band or DEFAULT_BAND_DIR_NAME


def _build_path_metadata(
    *,
    final_path: Path,
    root_dir: Path,
    workspace_root: Path,
    storage_mode: str,
    fallback_used: bool,
) -> dict[str, Any]:
    stored_path = _best_effort_relative_path(final_path, workspace_root)
    if not stored_path:
        try:
            stored_path = final_path.relative_to(root_dir).as_posix()
        except Exception:
            stored_path = final_path.name
    return {
        "screenshot_path": stored_path,
        "screenshot_abs_path": str(final_path.resolve()),
        "screenshot_root_dir": str(root_dir.resolve()),
        "screenshot_storage_mode": storage_mode,
        "screenshot_fallback_used": bool(fallback_used),
    }


def _best_effort_relative_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        try:
            return os.path.relpath(str(path.resolve()), str(base.resolve())).replace("\\", "/")
        except Exception:
            return ""


def _build_file_name(*, case: Any, result_id: str) -> str:
    parts = [
        _slug(str(getattr(case, "standard", "") or "")),
        _slug(str(getattr(case, "test_type", "") or "")),
        _format_bw_token(getattr(case, "bw_mhz", "")),
        _format_channel_token(getattr(case, "channel", "")),
        _format_voltage_token(case),
        _slug(str(result_id or ""))[:8],
    ]
    safe_parts = [part for part in parts if part]
    return "_".join(safe_parts) + DEFAULT_SCREENSHOT_EXTENSION


def _format_bw_token(value: Any) -> str:
    safe_value = _slug(str(value or ""))
    return f"{DEFAULT_BW_TOKEN}{safe_value}" if safe_value else DEFAULT_BW_TOKEN


def _format_channel_token(value: Any) -> str:
    safe_value = _slug(str(value or ""))
    return f"{DEFAULT_CHANNEL_TOKEN}{safe_value}" if safe_value else DEFAULT_CHANNEL_TOKEN


def _format_voltage_token(case: Any) -> str:
    tags = _case_tags(case)
    voltage_condition = _slug(str(tags.get("voltage_condition", "") or ""))
    target_voltage_v = tags.get("target_voltage_v")
    target_token = _format_voltage_value_token(target_voltage_v)
    if voltage_condition and target_token:
        return f"{voltage_condition}_{target_token}"
    if target_token:
        return target_token
    if voltage_condition:
        return voltage_condition
    return DEFAULT_VOLTAGE_TOKEN


def _format_voltage_value_token(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        normalized = f"{float(value):g}v"
    except Exception:
        normalized = f"{value}v"
    return _slug(normalized)


def _case_tags(case: Any) -> dict[str, Any]:
    try:
        return dict(getattr(case, "tags", {}) or {})
    except Exception:
        return {}


def _slug(text: str) -> str:
    safe: list[str] = []
    for ch in str(text or "").strip():
        if ch.isalnum():
            safe.append(ch.lower())
        elif ch in ("-", "_", "."):
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe).strip("_")


def _capture_payload(session: Any, strategy: dict[str, Any]) -> bytes:
    if str(strategy.get("name", "")) == "keysight_xseries":
        return _capture_payload_keysight_mmem(session)
    for cmd in strategy.get("prep_commands", ()):
        try:
            session.write(cmd)
        except Exception:
            continue
    for cmd in strategy.get("query_commands", ()):
        try:
            return _query_binary(session, cmd)
        except Exception as exc:
            log.info("screenshot query candidate failed | strategy=%s cmd=%s err=%s", strategy.get("name", ""), cmd, exc)
    raise RuntimeError(f"no screenshot SCPI command succeeded for strategy={strategy.get('name', '')}")


def _capture_payload_keysight_mmem(session: Any) -> bytes:
    instrument_path = _build_instrument_screenshot_path()
    commands = (
        f':MMEM:STOR:SCR "{instrument_path}"',
        f'MMEM:STOR:SCR "{instrument_path}"',
    )
    last_error = ""
    for cmd in commands:
        try:
            session.write(cmd)
            _wait_for_keysight_store_complete(session, instrument_path=instrument_path)
            return _query_binary(session, f':MMEM:DATA? "{instrument_path}"')
        except Exception as exc:
            last_error = str(exc)
            log.info("keysight screenshot store/read candidate failed | cmd=%s err=%s", cmd, exc)
            try:
                return _query_binary(session, f'MMEM:DATA? "{instrument_path}"')
            except Exception as read_exc:
                last_error = str(read_exc)
                log.info("keysight screenshot read candidate failed | path=%s err=%s", instrument_path, read_exc)
    raise RuntimeError(f"keysight MMEM screenshot capture failed | path={instrument_path} err={last_error}")


def _build_instrument_screenshot_path() -> str:
    return f"{DEFAULT_INSTRUMENT_SCREENSHOT_DIR}\\codex_capture.png"


def _coerce_settle_ms(value: int | float) -> int:
    try:
        return max(0, int(float(value)))
    except Exception:
        return DEFAULT_SCREENSHOT_SETTLE_MS


def _settle_before_capture(session: Any, *, settle_ms: int | float) -> None:
    settle_value_ms = _coerce_settle_ms(settle_ms)
    opc_ok = False
    if hasattr(session, "query"):
        try:
            response = str(session.query("*OPC?") or "").strip()
            opc_ok = response in {"1", "+1"}
            log.info("screenshot settle opc | response=%s settle_ms=%s", response, settle_value_ms)
        except Exception as exc:
            log.info("screenshot settle opc skipped | settle_ms=%s err=%s", settle_value_ms, exc)
    if settle_value_ms > 0:
        time.sleep(float(settle_value_ms) / 1000.0)
        log.info("screenshot settle sleep | settle_ms=%s opc_ok=%s", settle_value_ms, opc_ok)


def _wait_for_keysight_store_complete(session: Any, *, instrument_path: str) -> None:
    opc_ok = False
    if hasattr(session, "query"):
        try:
            response = str(session.query("*OPC?") or "").strip()
            opc_ok = response in {"1", "+1"}
            log.info(
                "keysight screenshot store sync | path=%s response=%s",
                instrument_path,
                response,
            )
        except Exception as exc:
            log.info(
                "keysight screenshot store sync fallback | path=%s err=%s",
                instrument_path,
                exc,
            )
    time.sleep(float(DEFAULT_POST_STORE_SETTLE_MS) / 1000.0)
    log.info(
        "keysight screenshot store settle | path=%s settle_ms=%s opc_ok=%s",
        instrument_path,
        DEFAULT_POST_STORE_SETTLE_MS,
        opc_ok,
    )


def _query_binary(session: Any, cmd: str) -> bytes:
    if hasattr(session, "query_binary_values"):
        try:
            payload = session.query_binary_values(cmd, datatype="B", container=bytes)
            if isinstance(payload, (bytes, bytearray)):
                return bytes(payload)
        except TypeError:
            values = session.query_binary_values(cmd, datatype="B")
            return bytes(values)
    if hasattr(session, "write") and hasattr(session, "read_raw"):
        session.write(cmd)
        return _strip_ieee_block(bytes(session.read_raw()))
    raise RuntimeError("session does not support binary query/read")


def _strip_ieee_block(payload: bytes) -> bytes:
    if not payload.startswith(b"#") or len(payload) < 3:
        return payload
    try:
        digits = int(chr(payload[1]))
        start = 2 + digits
        size = int(payload[2:start].decode("ascii"))
        end = start + size
        return payload[start:end]
    except Exception:
        return payload
