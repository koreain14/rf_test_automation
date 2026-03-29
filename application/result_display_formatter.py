from __future__ import annotations

from typing import Any, Dict

from application.plan_control_meta import build_run_display_context


def _fmt_run_context(data: Dict[str, Any]) -> str:
    ctx = build_run_display_context(data)
    path = data.get("switch_path") or data.get("path") or ctx.get("switch_path") or "(none)"
    ant = data.get("antenna") or ctx.get("antenna") or "(none)"
    power_txt = ctx.get("power_text") or "OFF"
    motion_txt = ctx.get("motion_text") or "MANUAL"
    dut_txt = ctx.get("dut_control_mode_text") or "MANUAL"
    display = data.get("_display") or {}
    exec_pol = display.get("execution_policy") or data.get("execution_policy") or {}
    order_pol = display.get("ordering_policy") or data.get("ordering_policy") or {}
    extra = []
    extra.append(f"DUT:{dut_txt}")
    if exec_pol:
        extra.append(f"EXEC:{exec_pol.get('type', 'FILTER_BASED')}")
    if order_pol:
        ob = order_pol.get("order_by") or []
        if ob:
            extra.append("ORDER:" + ",".join(str(x) for x in ob))
    suffix = (" | " + " | ".join(extra)) if extra else ""
    return f"PATH:{path} | ANT:{ant} | PSU:{power_txt} | MOTION:{motion_txt}{suffix}"


def format_step_result_row(step_row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(step_row)
    data = dict(step_row.get("data") or {})
    step_name = str(step_row.get("step_name", ""))
    if step_name == "EXECUTION_MODEL":
        out["display_data"] = f"standard={data.get('standard','')} | test={data.get('test_type','')} | steps={data.get('step_count',0)}"
    elif step_name == "EXECUTOR_PREVIEW":
        items = list(data.get("items") or [])
        statuses = ", ".join(f"{i.get('test_type','')}:{i.get('status','')}" for i in items[:6])
        out["display_data"] = statuses or "(no preview items)"
    elif step_name == "RUN_CONTEXT":
        out["display_data"] = _fmt_run_context(data)
    else:
        out["display_data"] = str(data)
    return out
