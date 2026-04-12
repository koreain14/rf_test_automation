from __future__ import annotations

from collections.abc import Iterable, Mapping

from domain.test_item_pool import get_test_item_pool, normalize_test_id


TEST_ITEM_POOL = get_test_item_pool()

CANONICAL_TEST_ITEMS: tuple[str, ...] = tuple(TEST_ITEM_POOL.keys())

TEST_ITEM_LABELS: dict[str, str] = {
    test_id: str(payload.get("display_name") or test_id)
    for test_id, payload in TEST_ITEM_POOL.items()
}

TEST_ITEM_ALIASES: dict[str, str] = {
    str(alias).strip().upper().replace("-", "_").replace(" ", "_"): test_id
    for test_id, payload in TEST_ITEM_POOL.items()
    for alias in ([test_id] + list(payload.get("aliases") or []))
    if str(alias).strip()
}


def _normalize_token(value: str | None) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def was_test_id_aliased(name: str | None) -> bool:
    token = _normalize_token(name)
    if not token:
        return False
    return token in TEST_ITEM_ALIASES and TEST_ITEM_ALIASES[token] != token


def normalize_test_id_list(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        normalized = normalize_test_id(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def normalize_test_id_map(values: Mapping[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (values or {}).items():
        normalized_key = normalize_test_id(key)
        if not normalized_key:
            continue
        out[normalized_key] = str(value)
    return out


def canonical_test_label(test_id: str | None) -> str:
    normalized = normalize_test_id(test_id)
    return TEST_ITEM_LABELS.get(normalized, normalized)
