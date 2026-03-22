# application/scheduler.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Tuple

from domain.models import TestCase


DEFAULT_TEST_ORDER = ["PSD", "OBW", "SP", "RX", "TXP", "DFS"]


@dataclass(frozen=True)
class ChannelCentricPolicy:
    """
    모드/대역/채널(+대역폭) 기준으로 묶고, 그룹 내부에서 test_type 순서대로 실행.
    """
    test_order: List[str] = None
    include_bw_in_group: bool = True  # True면 (std, band, ch, bw)로 고정 후 test_type 수행

    def __post_init__(self):
        if self.test_order is None:
            object.__setattr__(self, "test_order", list(DEFAULT_TEST_ORDER))


def _order_index_map(order: List[str]) -> Dict[str, int]:
    return {t: i for i, t in enumerate(order)}


def reorder_cases_channel_centric(
    cases: Iterable[TestCase],
    policy: ChannelCentricPolicy | None = None,
) -> List[TestCase]:
    """
    MVP 버전: cases를 List로 받아 정렬해서 반환.
    - 케이스 개수가 아주 커지면(수십만~) streaming/group iterator로 바꾸면 됨.
    """
    policy = policy or ChannelCentricPolicy()
    idx = _order_index_map(policy.test_order)

    def test_rank(t: str) -> int:
        return idx.get(t, 10_000)  # order에 없으면 뒤로

    def key(c: TestCase) -> Tuple:
        # 그룹 키: (standard, band, channel, bw?) 고정 → test_type 순서
        if policy.include_bw_in_group:
            group_key = (c.standard, c.band, c.channel, c.bw_mhz)
        else:
            group_key = (c.standard, c.band, c.channel)
        return (*group_key, test_rank(c.test_type), c.test_type, c.key)

    return sorted(list(cases), key=key)