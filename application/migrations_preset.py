from __future__ import annotations
from typing import Any, Dict, Tuple

LATEST_PRESET_SCHEMA = 3

def detect_schema_version(pj: Dict[str, Any]) -> int:
    # 1) explicit schema_version
    if "schema_version" in pj:
        return int(pj["schema_version"])
    # 2) selection이 있으면 이미 v1 이상 구조
    if isinstance(pj.get("selection"), dict):
        return 1
    # 3) 그 외는 v0
    return 0


def migrate_preset_to_latest(pj: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    return: (migrated_json, changed)
    """
    v = detect_schema_version(pj)
    changed = False

    # v0: 아주 구형 - selection 래핑이 없고 키가 최상단에 흩어져 있을 수 있음
    #     또는 name/ruleset_id 자체가 없을 수 있음
    if v == 0:
        pj = _migrate_v0_to_v1(pj)
        v = 1
        changed = True

    # v1 -> v2: execution_policy 기본값 보장 + schema_version 고정
    if v == 1:
        pj = _migrate_v1_to_v2(pj)
        v = 2
        changed = True

    if v == 2:
        pj = _migrate_v2_to_v3(pj)
        v = 3
        changed = True

    # 방어: 미래 버전이 들어오면 그대로 두되, 최소 필수 키가 없으면 에러
    if v > LATEST_PRESET_SCHEMA:
        _validate_minimum(pj)
        return pj, False

    _validate_minimum(pj)
    return pj, changed


def _migrate_v0_to_v1(pj: Dict[str, Any]) -> Dict[str, Any]:
    # v0에서는 selection이 없을 수 있음 → 전부 selection으로 감싼다
    selection = dict(pj)

    name = selection.pop("name", None) or "UnnamedPreset"
    ruleset_id = selection.pop("ruleset_id", None) or "KC_WLAN"
    ruleset_version = selection.pop("ruleset_version", None) or "2026.02"
    desc = selection.pop("description", "")

    return {
        "schema_version": 1,
        "name": name,
        "ruleset_id": ruleset_id,
        "ruleset_version": ruleset_version,
        "selection": selection,
        "description": desc,
    }


def _migrate_v1_to_v2(pj: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(pj)
    out["schema_version"] = 2

    sel = out.setdefault("selection", {})

    # execution_policy 없으면 기본값 부여 (channel-centric 기본)
    sel.setdefault("execution_policy", {
        "type": "CHANNEL_CENTRIC",
        "test_order": ["PSD", "OBW", "SP", "RX"],
        "include_bw_in_group": True
    })

    return out


def _validate_minimum(pj: Dict[str, Any]) -> None:
    for k in ("name", "ruleset_id", "ruleset_version", "selection", "schema_version"):
        if k not in pj:
            raise ValueError(f"Invalid preset json: missing '{k}'")

    sel = pj["selection"]
    for k in ("band", "test_types"):
        if k not in sel:
            raise ValueError(f"Invalid preset selection: missing '{k}'")

    has_wlan = bool((sel.get("wlan_expansion") or {}).get("mode_plan") or (sel.get("wlan_expansion") or {}).get("channel_plan"))
    has_legacy = all(k in sel for k in ("standard", "bandwidth_mhz", "channels"))
    if not (has_wlan or has_legacy):
        raise ValueError("Invalid preset selection: requires wlan_expansion or legacy standard/bandwidth_mhz/channels fields")

def _migrate_v2_to_v3(pj: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(pj)
    out["schema_version"] = 3
    sel = dict(out.get("selection") or {})

    wlan = sel.get("wlan_expansion")
    if not wlan:
        wlan = dict(sel.get("metadata") or {}).get("wlan_expansion")
    if wlan:
        sel["wlan_expansion"] = wlan

    sel.pop("metadata", None)
    sel.pop("bandwidth_mhz", None)
    sel.pop("channels", None)

    out["selection"] = sel
    return out
