from __future__ import annotations

from typing import Any, Dict, Tuple


CompareIdentityKey = Tuple[str, str, str, str, str, str, str, str, str]


_COMPARE_IDENTITY_FIELDS = (
    "test_key",
    "test_type",
    "band",
    "standard",
    "channel",
    "bw_mhz",
    "data_rate",
    "voltage_condition",
    "target_voltage_v",
)


def compare_identity_fields() -> Tuple[str, ...]:
    return _COMPARE_IDENTITY_FIELDS


def build_compare_identity_key(row: Dict[str, Any]) -> CompareIdentityKey:
    return tuple(str(row.get(field, "") or "") for field in _COMPARE_IDENTITY_FIELDS)  # type: ignore[return-value]


__all__ = [
    "CompareIdentityKey",
    "compare_identity_fields",
    "build_compare_identity_key",
]
