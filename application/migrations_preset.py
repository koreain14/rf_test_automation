from __future__ import annotations
from typing import Any, Dict, Tuple

LATEST_PRESET_SCHEMA = 2

def detect_schema_version(pj: Dict[str, Any]) -> int:
    # schema_version이 없으면 구버전(=0)으로 간주
    return int(pj.get("schema_version", 0))


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
    # 최소한 band/standard/test_types/bandwidth/channels 는 있어야 Plan 생성 가능
    for k in ("band", "standard", "test_types", "bandwidth_mhz", "channels"):
        if k not in sel:
            raise ValueError(f"Invalid preset selection: missing '{k}'")