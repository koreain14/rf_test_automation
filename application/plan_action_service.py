from __future__ import annotations

from typing import Iterable


class PlanActionService:
    """Design-level bulk filtered action helper.

    UI integration is intentionally minimal in this version. The service exposes
    include/exclude and enable/disable operations for future bulk filtered
    actions without changing the current public UI contract.
    """

    def exclude_case_keys(self, ctx, case_keys: Iterable[str]) -> None:
        target = set(case_keys)
        ctx.case_excluded.update(target)

    def include_case_keys(self, ctx, case_keys: Iterable[str]) -> None:
        target = set(case_keys)
        ctx.case_excluded.difference_update(target)

    def disable_case_keys(self, ctx, case_keys: Iterable[str]) -> None:
        for key in case_keys:
            ctx.case_enabled[str(key)] = False

    def enable_case_keys(self, ctx, case_keys: Iterable[str]) -> None:
        for key in case_keys:
            ctx.case_enabled.pop(str(key), None)

    def set_priority_tag(self, ctx, case_keys: Iterable[str], tag: str) -> None:
        for key in case_keys:
            ctx.case_priority_tags[str(key)] = tag
