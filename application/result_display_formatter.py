from __future__ import annotations

from typing import Any, Dict

from application.plan_control_meta import build_run_display_context


def _fmt_run_context(data: Dict[str, Any]) -> str:
    path = data.get("switch_path") or data.get("path") or "(none)"
    ant = data.get("antenna") or "(none)"
    power = data.get("power_control") or {}
    motion = data.get("motion_control") or {}
    psu = "OFF"
    if isinstance(power, dict) and power:
        if power.get("output_on"):
            psu = f"ON {power.get('voltage', '')}".strip()
        elif power.get("enabled"):
            psu = f"CFG {power.get('voltage', '')}".strip()
    motion_txt = "MANUAL"
    if isinstance(motion, dict) and motion:
        az = motion.get("turntable_angle_deg")
        ht = motion.get("mast_height_cm")
        parts = []
        if az not in (None, ""):
            parts.append(f"AZ:{az}")
        if ht not in (None, ""):
            parts.append(f"H:{ht}")
        if parts:
            motion_txt = " ".join(parts)
    display = data.get("_display") or {}
    exec_pol = display.get("execution_policy") or data.get("execution_policy") or {}
    order_pol = display.get("ordering_policy") or data.get("ordering_policy") or {}
    extra = []
    if exec_pol:
        extra.append(f"EXEC:{exec_pol.get('type', 'FILTER_BASED')}")
    if order_pol:
        ob = order_pol.get("order_by") or []
        if ob:
            extra.append("ORDER:" + ",".join(str(x) for x in ob))
    suffix = (" | " + " | ".join(extra)) if extra else ""
    return f"PATH:{path} | ANT:{ant} | PSU:{psu} | MOTION:{motion_txt}{suffix}"


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
