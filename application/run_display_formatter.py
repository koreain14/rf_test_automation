from __future__ import annotations

from typing import Any, Dict

from application.plan_control_meta import build_run_display_context, build_status_suffix, build_progress_suffix


def _render_case_bits(case: Dict[str, Any] | None) -> str:
    if not case:
        return ""
    parts = []
    test_type = str(case.get("test_type") or "").strip()
    channel = case.get("channel")
    voltage_condition = str(case.get("voltage_condition") or "").strip()
    target_voltage_v = case.get("target_voltage_v")
    target_voltage_text = ""
    try:
        if target_voltage_v not in (None, ""):
            target_voltage_text = f"{float(target_voltage_v):g}V"
    except Exception:
        target_voltage_text = str(target_voltage_v or "").strip()
    if channel not in (None, ""):
        parts.append(f"CH{channel}")
    if test_type:
        parts.append(test_type)
    if voltage_condition:
        parts.append(voltage_condition)
    if target_voltage_text:
        parts.append(target_voltage_text)
    return " | ".join(parts)


def build_status_text(
    run_id: str,
    meta: dict | None,
    *,
    state: str = "RUNNING",
    progress: str = "",
    counts: str = "",
    last_status: str = "",
    case: Dict[str, Any] | None = None,
) -> str:
    suffix = build_status_suffix(meta)
    base = f"{state} {run_id[:8] if run_id else '--------'}{suffix}"
    tail = []
    case_bits = _render_case_bits(case)
    if progress:
        tail.append(progress)
    if case_bits:
        tail.append(case_bits)
    if counts:
        tail.append(counts)
    if last_status:
        tail.append(f"last={last_status}")
    if tail:
        base += " | " + " | ".join(tail)
    return base


def build_progress_text(current: int, total: int, case: Dict[str, Any] | None, meta: dict | None) -> str:
    head = f"{current} / {total}" if total > 0 else str(current)
    case_bits = _render_case_bits(case)
    suffix = build_progress_suffix(meta)
    if case_bits:
        return f"{head} | {case_bits}{suffix}"
    return f"{head}{suffix}"


def build_plan_summary_lines(preset_name: str, meta: dict | None, execution_order: list[str]) -> str:
    ctx = build_run_display_context(meta)
    return (
        f"Preset: {preset_name}\n"
        f"Execution Order: {', '.join(execution_order)}\n"
        f"Switch Path: {ctx['switch_path'] or '(None)'}\n"
        f"Antenna: {ctx['antenna'] or '(None)'}\n"
        f"Power: {ctx['power_text'] or '(Default)'}\n"
        f"Motion: {ctx['motion_text'] or '(Default)'}\n"
        f"DUT Control: {ctx.get('dut_control_mode_text') or 'MANUAL'}"
    )
