# application/runner_step.py
from __future__ import annotations
import logging
from typing import Callable, Iterable, Optional, Tuple

from application.instrument_profile_resolver import InstrumentProfileResolver
from application.measurement_profile_runtime import build_consumable_measurement_profile
from application.procedures import ProcedureRegistry
from application.steps_dut import DutConfigureStep
from application.test_type_symbols import default_profile_for_test_type
from application.test_type_symbols import normalize_profile_name
from domain.models import TestCase
from domain.steps import CaseContext

log = logging.getLogger(__name__)


def _dut_group_key(c: TestCase) -> Tuple:
    # DUT 변경 최소화를 위한 그룹 키
    return (c.standard, c.band, c.channel, c.bw_mhz)


class StepRunner:
    def __init__(self, procedures: ProcedureRegistry, sink):
        self.procedures = procedures
        self.sink = sink  # sink.write(result_id, StepResult)
        self.profile_resolver = InstrumentProfileResolver()

    def run_case(self, result_id: str, case, inst) -> dict:
        ctx = CaseContext(case=case)
        instrument_snapshot = dict(getattr(case, "instrument", {}) or {})
        requested_profile_name = normalize_profile_name(
            instrument_snapshot.get("profile_name")
            or dict(getattr(case, "tags", {}) or {}).get("measurement_profile_name")
            or default_profile_for_test_type(getattr(case, "test_type", ""))
        )
        resolved_profile = self.profile_resolver.resolve_for_test_type(
            requested_profile_name,
            getattr(case, "test_type", ""),
        )
        ctx.values["resolved_profile"] = build_consumable_measurement_profile(
            test_type=getattr(case, "test_type", ""),
            resolved_profile=resolved_profile,
            instrument_snapshot=instrument_snapshot,
            resolver=self.profile_resolver,
        )
        ctx.values["measurement_profile_name"] = (
            ctx.values["resolved_profile"].get("profile_name") or requested_profile_name
        )
        ctx.values["measurement_profile_source"] = ctx.values["resolved_profile"].get("profile_source", "")
        log.info(
            "run_case measurement profile resolved | case=%s test_type=%s requested_profile=%s case_profile=%s tag_profile=%s resolved_profile=%s profile_source=%s trace_mode=%s detector=%s span_hz=%s rbw_hz=%s vbw_hz=%s sweep_time_s=%s avg_count=%s average_enabled=%s psd_result_unit=%s",
            getattr(case, "key", ""),
            getattr(case, "test_type", ""),
            requested_profile_name,
            instrument_snapshot.get("profile_name", ""),
            dict(getattr(case, "tags", {}) or {}).get("measurement_profile_name", ""),
            ctx.values["resolved_profile"].get("profile_name", ""),
            ctx.values["resolved_profile"].get("profile_source", ""),
            ctx.values["resolved_profile"].get("trace_mode", ""),
            ctx.values["resolved_profile"].get("detector", ""),
            ctx.values["resolved_profile"].get("span_hz", ""),
            ctx.values["resolved_profile"].get("rbw_hz", ""),
            ctx.values["resolved_profile"].get("vbw_hz", ""),
            ctx.values["resolved_profile"].get("sweep_time_s", ""),
            ctx.values["resolved_profile"].get("avg_count", ""),
            ctx.values["resolved_profile"].get("average_enabled", ctx.values["resolved_profile"].get("average", "")),
            dict(getattr(case, "tags", {}) or {}).get("psd_result_unit", ""),
        )
        procedure = self.procedures.get_procedure(case.test_type)
        ctx.values["procedure_name"] = getattr(procedure, "name", case.test_type)
        return procedure.execute(ctx, inst, self.sink, result_id)

    def run_cases(
        self,
        cases: Iterable[TestCase],
        inst,
        dut,
        should_stop: Callable[[], bool],
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        prev_key = None
        count = 0

        for case in cases:
            if should_stop():
                break

            cur_key = _dut_group_key(case)

            # ✅ 그룹 변경 시에만 DUT 설정
            if prev_key is None or cur_key != prev_key:
                ctx = CaseContext(case=case)
                dut_step = DutConfigureStep({
                    "standard": case.standard,
                    "band": case.band,
                    "channel": case.channel,
                    "bw_mhz": case.bw_mhz,
                })
                r = dut_step.run(ctx, dut)
                self.sink(case, r)
                if r.status == "ERROR":
                    break

                prev_key = cur_key

            values = self.run_case(case, inst)
            verdict = values.get("verdict", "ERROR")

            count += 1
            if on_progress and (count % 20 == 0):
                on_progress(count, verdict)
