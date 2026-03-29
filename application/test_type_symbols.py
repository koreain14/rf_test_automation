from __future__ import annotations

from collections.abc import Iterable, Mapping


CANONICAL_TEST_TYPES: tuple[str, ...] = (
    "PSD",
    "OBW",
    "SP",
    "RX",
    "CHANNEL_POWER",
    "FE",
)

RULESET_WLAN_TEST_TYPES: tuple[str, ...] = (
    "PSD",
    "OBW",
    "SP",
    "RX",
)

DEFAULT_TEST_ORDER: tuple[str, ...] = (
    "PSD",
    "OBW",
    "SP",
    "RX",
)

PLAN_FILTER_TEST_TYPES: tuple[str, ...] = (
    "PSD",
    "OBW",
    "SP",
    "RX",
    "CHANNEL_POWER",
    "FE",
)

TEST_TYPE_ALIASES: dict[str, str] = {
    "POWER_SPECTRAL_DENSITY": "PSD",
    "OCCUPIED_BANDWIDTH": "OBW",
    "TX_SPURIOUS": "SP",
    "RX_SPURIOUS": "RX",
    "FREQUENCY_ERROR": "FE",
    "TXP": "CHANNEL_POWER",
}

TEST_TYPE_UI_LABELS: dict[str, str] = {
    "PSD": "PSD",
    "OBW": "OBW",
    "SP": "SP",
    "RX": "RX",
    "CHANNEL_POWER": "CHANNEL_POWER",
    "FE": "FE",
}

TEST_TYPE_PROFILE_DEFAULTS: dict[str, str] = {
    "PSD": "PSD_DEFAULT",
    "OBW": "OBW_DEFAULT",
    "SP": "SP_DEFAULT",
    "RX": "RX_DEFAULT",
    "CHANNEL_POWER": "TXP_DEFAULT",
    "FE": "SP_DEFAULT",
}

PROFILE_NAME_ALIASES: dict[str, str] = {
    "RX_DEFAULT": "SP_DEFAULT",
}

TEST_TYPE_REQUIRED_CAPABILITIES: dict[str, list[str]] = {
    "PSD": ["analyzer"],
    "OBW": ["analyzer"],
    "SP": ["analyzer"],
    "RX": ["analyzer"],
    "CHANNEL_POWER": ["analyzer"],
    "FE": ["analyzer"],
}


def normalize_test_type_symbol(value: str | None) -> str:
    key = str(value or "").strip().upper()
    if not key:
        return ""
    return TEST_TYPE_ALIASES.get(key, key)


def normalize_test_type_list(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        normalized = normalize_test_type_symbol(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def normalize_test_type_map(values: Mapping[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (values or {}).items():
        normalized_key = normalize_test_type_symbol(key)
        if not normalized_key:
            continue
        out[normalized_key] = str(value)
    return out


def normalize_profile_name(profile_name: str | None) -> str:
    name = str(profile_name or "").strip()
    if not name:
        return ""
    return PROFILE_NAME_ALIASES.get(name, name)


def default_profile_for_test_type(test_type: str | None) -> str:
    normalized = normalize_test_type_symbol(test_type)
    profile_name = TEST_TYPE_PROFILE_DEFAULTS.get(normalized, "")
    return normalize_profile_name(profile_name)


def required_capabilities_for_test_type(test_type: str | None) -> list[str]:
    normalized = normalize_test_type_symbol(test_type)
    return list(TEST_TYPE_REQUIRED_CAPABILITIES.get(normalized, ()))


def canonical_supported_test_types(values: Iterable[str] | None) -> list[str]:
    return normalize_test_type_list(values)
