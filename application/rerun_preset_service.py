from __future__ import annotations

from typing import Any, Dict, List

from application.rerun_selection_builder import build_rerun_selection
from application.test_type_symbols import DEFAULT_TEST_ORDER, normalize_test_type_list
from domain.models import TestCase


class RerunPresetService:
    def __init__(self, owner):
        self.owner = owner

    @property
    def repo(self):
        return self.owner.repo

    @property
    def run_repo(self):
        return self.owner.run_repo

    def create_skip_override_for_case(self, project_id: str, preset_id: str, case: TestCase, priority: int = 100) -> str:
        override_json = {
            "name": f"SKIP {case.test_type} CH{case.channel} BW{case.bw_mhz}",
            "enabled": True,
            "priority": priority,
            "match": {
                "band": case.band,
                "standard": case.standard,
                "test_type": case.test_type,
                "channel": case.channel,
                "bw_mhz": case.bw_mhz,
            },
            "action": "skip",
            "set_values": {},
        }
        return self.repo.save_override(
            project_id=project_id,
            preset_id=preset_id,
            name=override_json["name"],
            override_json=override_json,
            priority=priority,
            enabled=True,
        )

    def create_skip_override_for_selection(
        self,
        project_id: str,
        preset_id: str,
        cases: List[TestCase],
        priority: int = 100,
    ) -> str:
        if not cases:
            raise ValueError("No cases")
        first = cases[0]
        for c in cases[1:]:
            if (c.band, c.standard, c.test_type, c.bw_mhz) != (first.band, first.standard, first.test_type, first.bw_mhz):
                raise ValueError("Selection not homogeneous (band/standard/test_type/bw must match for grouped skip)")
        channels = sorted({c.channel for c in cases})
        override_json = {
            "name": f"SKIP {first.test_type} BW{first.bw_mhz} CH{channels[0]}..({len(channels)}ch)",
            "enabled": True,
            "priority": priority,
            "match": {
                "band": first.band,
                "standard": first.standard,
                "test_type": first.test_type,
                "bw_mhz": first.bw_mhz,
                "channels": channels,
            },
            "action": "skip",
            "set_values": {},
        }
        return self.repo.save_override(
            project_id=project_id,
            preset_id=preset_id,
            name=override_json["name"],
            override_json=override_json,
            priority=priority,
            enabled=True,
        )

    def create_rerun_preset_from_fail(self, project_id: str, base_preset_id: str, run_id: str) -> str:
        base = self.repo.load_preset(preset_id=base_preset_id)
        failed = self.run_repo.get_failed_cases(project_id=project_id, run_id=run_id)
        if not failed:
            raise ValueError("No FAIL cases found in this run.")
        base_selection = dict(base["selection"]) if "selection" in base else dict(base)
        selection = build_rerun_selection(
            base_selection=base_selection,
            selected_rows=failed,
        )
        rerun_name = f"RERUN_{run_id[:8]}_{base.get('name', 'preset')}"
        rerun_json = {
            "name": rerun_name,
            "ruleset_id": base.get("ruleset_id", "KC_WLAN"),
            "ruleset_version": base.get("ruleset_version", "2026.02"),
            "selection": selection,
            "description": f"Auto-generated re-run from FAILs of run {run_id}",
        }
        return self.repo.save_preset(
            project_id=project_id,
            name=rerun_json["name"],
            ruleset_id=rerun_json["ruleset_id"],
            ruleset_version=rerun_json["ruleset_version"],
            preset_json=rerun_json,
        )

    def create_rerun_preset_from_selected_results(
        self,
        project_id: str,
        base_preset_id: str,
        selected_rows: List[Dict[str, Any]],
    ) -> str:
        if not selected_rows:
            raise ValueError("No rows selected.")
        base = self.repo.load_preset(preset_id=base_preset_id)
        base_selection = dict(base["selection"]) if "selection" in base else dict(base)
        selection = build_rerun_selection(
            base_selection=base_selection,
            selected_rows=selected_rows,
        )
        base_name = base.get("name", "preset")
        rerun_name = f"RERUN_SEL_{base_name}"
        rerun_json = {
            "name": rerun_name,
            "ruleset_id": base.get("ruleset_id", "KC_WLAN"),
            "ruleset_version": base.get("ruleset_version", "2026.02"),
            "selection": selection,
            "description": "Auto-generated re-run from selected results",
        }
        return self.repo.save_preset(
            project_id=project_id,
            name=rerun_json["name"],
            ruleset_id=rerun_json["ruleset_id"],
            ruleset_version=rerun_json["ruleset_version"],
            preset_json=rerun_json,
        )

    def save_execution_order(self, preset_id: str, test_order: List[str]) -> None:
        pj = self.repo.load_preset(preset_id=preset_id)
        if "selection" not in pj:
            selection = dict(pj)
            pj = {
                "name": selection.get("name", "UnnamedPreset"),
                "ruleset_id": selection.get("ruleset_id", "KC_WLAN"),
                "ruleset_version": selection.get("ruleset_version", "2026.02"),
                "selection": selection,
                "description": selection.get("description", ""),
            }
        sel = pj.setdefault("selection", {})
        sel["execution_policy"] = {
            "type": "CHANNEL_CENTRIC",
            "test_order": normalize_test_type_list(test_order) or list(DEFAULT_TEST_ORDER),
            "include_bw_in_group": True,
        }
        self.repo.update_preset_json(preset_id=preset_id, preset_json=pj)

    def create_rerun_preset_from_result_rows(
        self,
        project_id: str,
        base_preset_id: str,
        selected_rows: List[Dict[str, Any]],
    ) -> str:
        return self.create_rerun_preset_from_selected_results(
            project_id=project_id,
            base_preset_id=base_preset_id,
            selected_rows=selected_rows,
        )
