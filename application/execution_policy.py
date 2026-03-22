from __future__ import annotations

from typing import Any, Dict, Iterable, List

from application.plan_models import ExecutionPolicy, OrderingPolicy


def execution_policy_from_meta(meta: Dict[str, Any] | None) -> ExecutionPolicy:
    raw = dict((meta or {}).get("execution_policy") or {})
    return ExecutionPolicy(
        type=str(raw.get("type", "FILTER_BASED") or "FILTER_BASED"),
        exclude_disabled=bool(raw.get("exclude_disabled", True)),
        exclude_excluded=bool(raw.get("exclude_excluded", True)),
    )


def ordering_policy_from_meta(meta: Dict[str, Any] | None) -> OrderingPolicy:
    raw = dict((meta or {}).get("ordering_policy") or {})
    order_by = tuple(raw.get("order_by") or ("band", "standard", "channel"))
    test_priority = tuple(raw.get("test_priority") or ("PSD", "OBW", "SP", "RX"))
    return OrderingPolicy(order_by=order_by, test_priority=test_priority)


def apply_execution_policy(rows: Iterable[Dict[str, Any]], policy: ExecutionPolicy) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        enabled = bool(row.get("enabled", True))
        excluded = bool(row.get("excluded", False))
        if policy.exclude_disabled and not enabled:
            continue
        if policy.exclude_excluded and excluded:
            continue
        out.append(row)
    return out


def sort_rows(rows: Iterable[Dict[str, Any]], policy: OrderingPolicy) -> List[Dict[str, Any]]:
    priority = {name: idx for idx, name in enumerate(policy.test_priority)}
    def _key(row: Dict[str, Any]):
        parts: List[Any] = []
        for field in policy.order_by:
            if field == "test_type":
                parts.append(priority.get(str(row.get("test_type", "")), 999))
            else:
                parts.append(row.get(field, ""))
        if "test_type" not in policy.order_by:
            parts.append(priority.get(str(row.get("test_type", "")), 999))
        parts.append(row.get("sort_index", 0))
        return tuple(parts)
    return sorted(list(rows), key=_key)
