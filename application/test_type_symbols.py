from __future__ import annotations

from collections.abc import Iterable, Mapping

from domain.test_item_pool import get_test_item_definition, list_available_test_items
from domain.test_item_registry import (
    CANONICAL_TEST_ITEMS,
    TEST_ITEM_LABELS,
    normalize_test_id,
    normalize_test_id_list,
    normalize_test_id_map,
)


CANONICAL_TEST_TYPES: tuple[str, ...] = tuple(CANONICAL_TEST_ITEMS)

RULESET_WLAN_TEST_TYPES: tuple[str, ...] = (
    "PSD",
    "OBW",
    "SP",
    "RX",
    "TXP",
)

DEFAULT_TEST_ORDER: tuple[str, ...] = (
    "PSD",
    "OBW",
    "SP",
    "RX",
    "TXP",
)

PLAN_FILTER_TEST_TYPES: tuple[str, ...] = (
    "PSD",
    "OBW",
    "SP",
    "RX",
    "TXP",
    "DFS",
    "FE",
)

TEST_TYPE_UI_LABELS: dict[str, str] = dict(TEST_ITEM_LABELS)

PROFILE_NAME_ALIASES: dict[str, str] = {
    "RX_DEFAULT": "SP_DEFAULT",
}


def normalize_test_type_symbol(value: str | None) -> str:
    return normalize_test_id(value)


def normalize_test_type_list(values: Iterable[str] | None) -> list[str]:
    return normalize_test_id_list(values)


def normalize_test_type_map(values: Mapping[str, str] | None) -> dict[str, str]:
    return normalize_test_id_map(values)


def normalize_profile_name(profile_name: str | None) -> str:
    name = str(profile_name or "").strip()
    if not name:
        return ""
    return PROFILE_NAME_ALIASES.get(name, name)


def default_profile_for_test_type(test_type: str | None) -> str:
    normalized = normalize_test_type_symbol(test_type)
    payload = get_test_item_definition(normalized) or {}
    profile_name = str(payload.get("default_profile_ref", "") or "")
    return normalize_profile_name(profile_name)


def required_capabilities_for_test_type(test_type: str | None) -> list[str]:
    normalized = normalize_test_type_symbol(test_type)
    payload = get_test_item_definition(normalized) or {}
    return [str(item).strip() for item in (payload.get("required_instruments") or []) if str(item).strip()]


def canonical_supported_test_types(values: Iterable[str] | None) -> list[str]:
    return normalize_test_id_list(values)


IMPLEMENTED_TEST_TYPES: tuple[str, ...] = tuple(
    item["id"] for item in list_available_test_items(selectable_only=True)
)
