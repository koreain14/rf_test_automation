# application/run_service.py

import logging
import random
import time
from typing import Callable, List, Optional, Tuple

from domain.models import OverrideRule, Recipe, RuleSet, TestCase
from domain.expand import expand_recipe
from domain.overrides import apply_overrides
from infrastructure.run_repo_sqlite import RunRepositorySQLite
from application.scheduler import reorder_cases_channel_centric, ChannelCentricPolicy
from application.test_type_symbols import DEFAULT_TEST_ORDER, normalize_test_type_list

log = logging.getLogger(__name__)


class RunService:
    """
    실제 장비 제어는 나중에 InstrumentManager로 분리.
    지금은 Dummy로 PASS/FAIL 플로우 + DB 저장 확인용.
    """

    def __init__(self, run_repo: RunRepositorySQLite):
        self.run_repo = run_repo

    def iter_cases(self, ruleset: RuleSet, recipe: Recipe, overrides: List[OverrideRule]):
        return apply_overrides(expand_recipe(ruleset, recipe), overrides)

    def dummy_judge(self, case: TestCase) -> Tuple[str, float]:
        """
        임의 FAIL 조건(플로우 검증용):
          - channel 116 이고 test_type == PSD면 FAIL
          - 나머지는 PASS
        """
        if case.channel == 116 and case.test_type == "PSD":
            return "FAIL", -1.5
        return "PASS", +3.0

    def run(
        self,
        project_id: str,
        preset_id: str,
        run_id: str,
        ruleset: RuleSet,
        recipe: Recipe,
        overrides: List[OverrideRule],
        should_stop: Callable[[], bool],
        on_progress: Optional[Callable[[int, str, dict | None], None]] = None,
        selected_case_keys: Optional[list[str]] = None,
    ) -> str:
        """
        return final status: DONE/ABORTED/ERROR
        """
        count = 0
        try:
            # execution_policy 읽기 (없으면 기본값)
            pol = (recipe.meta or {}).get("execution_policy") or {}
            order = normalize_test_type_list(pol.get("test_order") or []) or list(DEFAULT_TEST_ORDER)
            include_bw = bool(pol.get("include_bw_in_group", True))

            policy = ChannelCentricPolicy(test_order=order, include_bw_in_group=include_bw)

            cases = self.iter_cases(ruleset, recipe, overrides)
            cases = reorder_cases_channel_centric(cases, policy)
            if selected_case_keys:
                selected_set = set(selected_case_keys)
                cases = [case for case in cases if case.key in selected_set]

            for case in cases:
                if should_stop():
                    return "ABORTED"

                tags = dict(getattr(case, "tags", {}) or {})
                current_case_info = {
                    "channel": case.channel,
                    "test_type": case.test_type,
                    "standard": case.standard,
                    "data_rate": tags.get("data_rate", ""),
                    "case_key": case.key,
                    "voltage_condition": tags.get("voltage_condition", ""),
                    "target_voltage_v": tags.get("target_voltage_v"),
                    "nominal_voltage_v": tags.get("nominal_voltage_v"),
                }
                if on_progress:
                    on_progress(count, "RUNNING", current_case_info)

                # dummy time
                time.sleep(0.01)

                status, margin = self.dummy_judge(case)

                self.run_repo.append_result(
                    project_id=project_id,
                    run_id=run_id,
                    row={
                        "test_key": case.key,
                        "tech": ruleset.tech,
                        "regulation": ruleset.regulation,
                        "band": case.band,
                        "standard": case.standard,
                        "test_type": case.test_type,
                        "channel": case.channel,
                        "bw_mhz": case.bw_mhz,
                        "status": status,
                        "margin_db": margin,
                        "instrument_snapshot": case.instrument,
                        "tags": case.tags,
                    }
                )

                count += 1
                if on_progress and (count % 20 == 0):
                    on_progress(count, status, current_case_info)

            return "DONE"
        except Exception:
            log.exception("RunService.run failed")
            return "ERROR"
