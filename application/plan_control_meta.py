from __future__ import annotations

from typing import Any, Dict


def _as_dict(meta: dict | None) -> dict:
    return dict(meta or {})


def get_rf_path(meta: dict | None) -> dict:
    data = _as_dict(meta).get("rf_path") or {}
    return dict(data) if isinstance(data, dict) else {}


def get_switch_path(meta: dict | None) -> str:
    rf = get_rf_path(meta)
    return str(rf.get("switch_path") or "")


def get_antenna(meta: dict | None) -> str:
    rf = get_rf_path(meta)
    return str(rf.get("antenna") or "")


def get_power(meta: dict | None) -> dict:
    data = _as_dict(meta).get("power_control") or {}
    return dict(data) if isinstance(data, dict) else {}


def get_motion(meta: dict | None) -> dict:
    data = _as_dict(meta).get("motion_control") or {}
    return dict(data) if isinstance(data, dict) else {}




def get_dut_control_mode(meta: dict | None) -> str:
    value = str(_as_dict(meta).get("dut_control_mode") or "manual").strip().lower()
    return value if value in {"manual", "auto_license", "auto_callbox"} else "manual"


def format_dut_control_mode(mode: str | None) -> str:
    value = str(mode or "manual").strip().lower()
    labels = {
        "manual": "MANUAL",
        "auto_license": "AUTO_LICENSE",
        "auto_callbox": "AUTO_CALLBOX",
    }
    return labels.get(value, "MANUAL")

def _fmt_num(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return ""
    if num.is_integer():
        return str(int(num))
    return f"{num:g}"


def format_power(power: dict | None) -> str:
    p = dict(power or {})
    if not p or not p.get("enabled"):
        return ""
    parts = ["PSU"]
    if p.get("output_on"):
        parts.append("ON")
    v = _fmt_num(p.get("voltage"))
    if v:
        parts.append(f"{v}V")
    c = _fmt_num(p.get("current_limit"))
    if c:
        parts.append(f"{c}A")
    return " ".join(parts)


def format_motion(motion: dict | None) -> str:
    m = dict(motion or {})
    if not m or not m.get("enabled"):
        return ""
    parts = ["MOTION"]
    az = _fmt_num(m.get("turntable_angle_deg"))
    h = _fmt_num(m.get("mast_height_cm"))
    if az:
        parts.append(f"AZ:{az}deg")
    if h:
        parts.append(f"H:{h}cm")
    return " ".join(parts)


def build_run_display_context(meta: dict | None) -> Dict[str, Any]:
    m = _as_dict(meta)
    switch_path = get_switch_path(m)
    antenna = get_antenna(m)
    power = get_power(m)
    motion = get_motion(m)
    dut_control_mode = get_dut_control_mode(m)
    return {
        "switch_path": switch_path,
        "antenna": antenna,
        "power": power,
        "motion": motion,
        "dut_control_mode": dut_control_mode,
        "power_text": format_power(power),
        "motion_text": format_motion(motion),
        "dut_control_mode_text": format_dut_control_mode(dut_control_mode),
    }


def build_status_suffix(meta: dict | None) -> str:
    ctx = build_run_display_context(meta)
    parts = []
    if ctx["switch_path"]:
        parts.append(f"PATH:{ctx['switch_path']}")
    if ctx["antenna"]:
        parts.append(f"ANT:{ctx['antenna']}")
    if ctx["power_text"]:
        parts.append(ctx["power_text"])
    if ctx["motion_text"]:
        parts.append(ctx["motion_text"])
    if ctx["dut_control_mode_text"]:
        parts.append(f"DUT:{ctx['dut_control_mode_text']}")
    return (" | " + " | ".join(parts)) if parts else ""


def build_progress_suffix(meta: dict | None) -> str:
    ctx = build_run_display_context(meta)
    parts = []
    if ctx["antenna"]:
        parts.append(f"ANT:{ctx['antenna']}")
    if ctx["power_text"]:
        parts.append(ctx["power_text"].replace("PSU ", "PSU:"))
    if ctx["dut_control_mode_text"]:
        parts.append(f"DUT:{ctx['dut_control_mode_text']}")
    return (" | " + " | ".join(parts)) if parts else ""
