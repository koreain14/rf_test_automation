import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from domain.models import (
    InstrumentProfile, Match, OverrideRule, Preset, Recipe, RuleSet, TestCase
)
from domain.expand import build_recipe, expand_recipe
from domain.overrides import apply_overrides
from infrastructure.plan_repo_sqlite import PlanRepositorySQLite
from infrastructure.run_repo_sqlite import RunRepositorySQLite
from application.migrations_preset import migrate_preset_to_latest
from domain.ruleset_models import BandInfo, PlanMode  # 경로는 너 프로젝트에 맞게
from dataclasses import dataclass




class PlanService:
    def __init__(self, repo: PlanRepositorySQLite, run_repo: RunRepositorySQLite, ruleset_dir: Path):
        self.repo = repo
        self.run_repo = run_repo
        self.ruleset_dir = ruleset_dir
        self._ruleset_cache: Dict[str, RuleSet] = {}

    # ---------- RuleSet ----------

    def load_ruleset(self, ruleset_id: str) -> RuleSet:
        if ruleset_id in self._ruleset_cache:
            return self._ruleset_cache[ruleset_id]

        path = self.ruleset_dir / f"{ruleset_id.lower()}.json"
        if not path.exists():
            alt = self.ruleset_dir / "kc_wlan.json"
            if alt.exists() and ruleset_id == "KC_WLAN":
                path = alt
            else:
                raise FileNotFoundError(f"RuleSet json not found for {ruleset_id}")

        raw = json.loads(path.read_text(encoding="utf-8"))

        # ✅ instrument_profiles: 기존 유지
        ips = {
            name: InstrumentProfile(name=name, settings=settings)
            for name, settings in (raw.get("instrument_profiles", {}) or {}).items()
        }

        # ✅ bands: dict -> BandInfo 객체로 정규화
        bands_raw: Dict[str, dict] = raw.get("bands", {}) or {}
        bands = {band_name: BandInfo.from_dict(band_name, band_dict) for band_name, band_dict in bands_raw.items()}

        # ✅ plan_modes: dict -> PlanMode 객체로 정규화
        pm_raw: Dict[str, dict] = raw.get("plan_modes", {}) or {}
        plan_modes = {mode_name: PlanMode.from_dict(mode_name, mode_dict) for mode_name, mode_dict in pm_raw.items()}

        rs = RuleSet(
            id=raw["id"],
            version=raw.get("version", ""),
            regulation=raw.get("regulation", ""),
            tech=raw.get("tech", ""),
            bands=bands,                    # <- 변경됨 (BandInfo dict)
            instrument_profiles=ips,
            plan_modes=plan_modes,          # <- 변경됨 (PlanMode dict)
        )

        self._ruleset_cache[ruleset_id] = rs
        return rs
    
    # ---------- Project/Preset ----------
    def list_projects(self) -> List[Dict[str, Any]]:
        return self.repo.list_projects()

    def ensure_demo_project_and_preset(self) -> Tuple[str, str]:
        """
        DB가 비어있으면 데모 프로젝트/프리셋 하나 만들어 UI가 바로 동작하게 함.
        반환: (project_id, preset_id)
        """
        projects = self.repo.list_projects()
        if projects:
            project_id = projects[0]["project_id"]
            presets = self.repo.list_presets(project_id)
            if presets:
                return project_id, presets[0]["preset_id"]

        project_id = self.repo.create_project("Model_KC_Test", "Demo project")
        preset_json = {
            "name": "KC_5G_UNII_LMH_Quick",
            "ruleset_id": "KC_WLAN",
            "ruleset_version": "2026.02",
            "selection": {
                "band": "5G",
                "standard": "802.11ac",
                "plan_mode": "Quick",
                "test_types": ["PSD", "OBW", "SP"],
                "bandwidth_mhz": [20, 80],
                "channels": {
                    "policy": "LOW_MID_HIGH_BY_GROUP",
                    "grouping": "UNII",
                    "groups": ["UNII-1", "UNII-2A", "UNII-2C", "UNII-3"],
                    "representatives_override": {
                        "UNII-2C": { "mid": 116 }
                    }
                },
                "instrument_profile_by_test": {
                    "PSD": "PSD_DEFAULT",
                    "OBW": "OBW_DEFAULT",
                    "SP": "SP_DEFAULT"
                }
            },
            "description": "Demo preset"
        }
        preset_id = self.repo.save_preset(
            project_id=project_id,
            name=preset_json["name"],
            ruleset_id=preset_json["ruleset_id"],
            ruleset_version=preset_json["ruleset_version"],
            preset_json=preset_json,
        )
        return project_id, preset_id

    def list_presets(self, project_id: str) -> List[Dict[str, Any]]:
        return self.repo.list_presets(project_id)

   
    def load_override_objs(self, preset_id: str) -> List[OverrideRule]:
        rows = self.repo.list_overrides(preset_id)
        out: List[OverrideRule] = []
        for r in rows:
            j = r["json_data"]
            m = j.get("match", {})
            out.append(
                OverrideRule(
                    name=j.get("name", r["name"]),
                    enabled=bool(j.get("enabled", r["enabled"])),
                    priority=int(j.get("priority", r["priority"])),
                    match=Match(
                        band=m.get("band"),
                        standard=m.get("standard"),
                        test_type=m.get("test_type"),
                        channel=m.get("channel"),
                        bw_mhz=m.get("bw_mhz"),
                        group=m.get("group"),
                        segment=m.get("segment"),
                        device_class=m.get("device_class"),
                        channels=m.get("channels"),
                    ),
                    action=j["action"],
                    set_values=j.get("set_values", {}),
                )
            )
        return out

    # ---------- Recipe/Cases ----------
    from typing import Tuple, List

    def build_recipe_from_preset(self, preset_id: str):
        preset = self.load_preset_obj(preset_id)
        if preset is None:
            raise KeyError(f"Preset not found: {preset_id}")

        ruleset = self.load_ruleset(preset.ruleset_id)  # 이제 RuleSet 객체로 확정

        self.validate_preset_against_ruleset(preset, ruleset)

        recipe = build_recipe(ruleset, preset)
        overrides = self.load_override_objs(preset_id) or []
        return ruleset, preset, recipe, overrides

    def iter_cases(
        self,
        ruleset: RuleSet,
        recipe: Recipe,
        overrides: List[OverrideRule],
        filter_: Optional[Dict[str, Any]] = None,
    ):
        cases = expand_recipe(ruleset, recipe)
        cases = apply_overrides(cases, overrides)

        if not filter_:
            yield from cases
            return

        for c in cases:
            ok = True
            if "test_type" in filter_ and c.test_type != filter_["test_type"]:
                ok = False
            if "bw_mhz" in filter_ and c.bw_mhz != filter_["bw_mhz"]:
                ok = False
            if ok:
                yield c
                
    def count_cases(self, ruleset, recipe, overrides, filter_=None) -> int:
        count = 0
        for _ in self.iter_cases(
            ruleset=ruleset,
            recipe=recipe,
            overrides=overrides,
            filter_=filter_,
        ):
            count += 1
        return count
    
    def get_cases_page(
        self,
        ruleset: RuleSet,
        recipe: Recipe,
        overrides: List[OverrideRule],
        filter_: Optional[Dict[str, Any]],
        offset: int,
        limit: int,
    ) -> List[TestCase]:
        """
        MVP용 단순 페이징: iterator를 offset+limit까지 소비.
        (나중에 대규모 최적화는 별도 캐시/인덱싱으로 개선)
        """
        out: List[TestCase] = []
        it = self.iter_cases(ruleset, recipe, overrides, filter_)
        i = 0
        for c in it:
            if i >= offset and len(out) < limit:
                out.append(c)
            i += 1
            if len(out) >= limit:
                break
        return out
    
   
  
    # ---------- Override helpers ----------
    def create_skip_override_for_case(
        self,
        project_id: str,
        preset_id: str,
        case: TestCase,
        priority: int = 100,
    ) -> str:
        override_json = {
            "name": f"SKIP {case.test_type} CH{case.channel} BW{case.bw_mhz}",
            "enabled": True,
            "priority": priority,
            "match": {
                "band": case.band,
                "standard": case.standard,
                "test_type": case.test_type,
                "channel": case.channel,
                "bw_mhz": case.bw_mhz
            },
            "action": "skip",
            "set_values": {}
        }
        return self.repo.save_override(
            project_id=project_id,
            preset_id=preset_id,
            name=override_json["name"],
            override_json=override_json,
            priority=priority,
            enabled=True
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
        # 공통성 검사
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
                "channels": channels
            },
            "action": "skip",
            "set_values": {}
        }
        return self.repo.save_override(
            project_id=project_id,
            preset_id=preset_id,
            name=override_json["name"],
            override_json=override_json,
            priority=priority,
            enabled=True
        )
        
    def create_rerun_preset_from_fail(self, project_id: str, base_preset_id: str, run_id: str) -> str:
        base = self.repo.load_preset(base_preset_id)
        failed = self.run_repo.get_failed_cases(project_id, run_id)

        if not failed:
            raise ValueError("No FAIL cases found in this run.")

        # 실패 케이스에서 필요한 최소 정보만 모아서 re-run selection 구성
        test_types = sorted({r["test_type"] for r in failed})
        bw_list = sorted({int(r["bw_mhz"]) for r in failed})
        channels = sorted({int(r["channel"]) for r in failed})

        # base preset이 신포맷이면 selection을 복사, 구포맷이면 base 자체를 selection으로 취급
        if "selection" in base:
            selection = dict(base["selection"])
        else:
            selection = dict(base)

        selection["test_types"] = test_types
        selection["bandwidth_mhz"] = bw_list
        selection["channels"] = {
            "policy": "CUSTOM_LIST",
            "channels": channels
        }

        rerun_name = f"RERUN_{run_id[:8]}_{base.get('name', 'preset')}"
        rerun_json = {
            "name": rerun_name,
            "ruleset_id": base.get("ruleset_id", "KC_WLAN"),
            "ruleset_version": base.get("ruleset_version", "2026.02"),
            "selection": selection,
            "description": f"Auto-generated re-run from FAILs of run {run_id}"
        }

        new_preset_id = self.repo.save_preset(
            project_id=project_id,
            name=rerun_json["name"],
            ruleset_id=rerun_json["ruleset_id"],
            ruleset_version=rerun_json["ruleset_version"],
            preset_json=rerun_json,
        )
        return new_preset_id
    
    def create_rerun_preset_from_selected_results(
        self,
        project_id: str,
        base_preset_id: str,
        selected_rows: List[Dict[str, Any]],
    ) -> str:
        """
        selected_rows: Results 테이블의 선택된 row dict 목록
        반드시 포함: test_type, channel, bw_mhz
        band/standard는 base preset에서 가져옴(선택 row에 있어도 무방)
        """
        if not selected_rows:
            raise ValueError("No rows selected.")

        base = self.repo.load_preset(base_preset_id)

        # base preset이 신포맷이면 selection을 복사, 구포맷이면 base 자체를 selection으로 취급
        if "selection" in base:
            selection = dict(base["selection"])
        else:
            selection = dict(base)

        # 선택된 row에서 필요한 값들 집계
        test_types = sorted({r["test_type"] for r in selected_rows if r.get("test_type")})
        bw_list = sorted({int(r["bw_mhz"]) for r in selected_rows if r.get("bw_mhz") is not None})
        channels = sorted({int(r["channel"]) for r in selected_rows if r.get("channel") is not None})

        if not test_types or not bw_list or not channels:
            raise ValueError("Selected rows must include test_type, bw_mhz, channel.")

        # selection을 re-run 형태로 덮어쓰기
        selection["test_types"] = test_types
        selection["bandwidth_mhz"] = bw_list
        selection["channels"] = {
            "policy": "CUSTOM_LIST",
            "channels": channels
        }

        base_name = base.get("name", "preset")
        rerun_name = f"RERUN_SEL_{base_name}"

        rerun_json = {
            "name": rerun_name,
            "ruleset_id": base.get("ruleset_id", "KC_WLAN"),
            "ruleset_version": base.get("ruleset_version", "2026.02"),
            "selection": selection,
            "description": "Auto-generated re-run from selected results"
        }

        new_preset_id = self.repo.save_preset(
            project_id=project_id,
            name=rerun_json["name"],
            ruleset_id=rerun_json["ruleset_id"],
            ruleset_version=rerun_json["ruleset_version"],
            preset_json=rerun_json,
        )
        return new_preset_id
    
    def save_execution_order(self, preset_id: str, test_order: List[str]) -> None:
        pj = self.repo.load_preset(preset_id)

        # 신/구 포맷 모두 처리
        if "selection" not in pj:
            selection = dict(pj)
            pj = {
                "name": selection.get("name", "UnnamedPreset"),
                "ruleset_id": selection.get("ruleset_id", "KC_WLAN"),
                "ruleset_version": selection.get("ruleset_version", "2026.02"),
                "selection": selection,
                "description": selection.get("description", "")
            }

        sel = pj.setdefault("selection", {})
        sel["execution_policy"] = {
            "type": "CHANNEL_CENTRIC",
            "test_order": list(test_order),
            "include_bw_in_group": True
        }

        self.repo.update_preset_json(preset_id, pj)
        
    def load_preset_obj(self, preset_id: str) -> Preset:
        pj = self.repo.load_preset(preset_id)

        migrated, changed = migrate_preset_to_latest(pj)

        # ✅ 옵션: 개발 중에는 최신으로 자동 저장해 DB를 깨끗하게 유지
        if changed:
            self.repo.update_preset_json(preset_id, migrated)

        return Preset(
            name=migrated["name"],
            ruleset_id=migrated["ruleset_id"],
            ruleset_version=migrated["ruleset_version"],
            selection=migrated["selection"],
            description=migrated.get("description", ""),
    )
        
    def validate_preset_against_ruleset(self, preset: Preset, ruleset: RuleSet) -> None:
        sel = preset.selection
        band = sel.get("band")
        standard = sel.get("standard")
        test_types = sel.get("test_types", [])
        channels = sel.get("channels", {})

        if band not in ruleset.bands:
            raise ValueError(f"Band '{band}' is not defined in RuleSet. Available: {list(ruleset.bands.keys())}")

        band_info = ruleset.bands[band]

        if standard not in band_info.standards:
            raise ValueError(f"Standard '{standard}' not supported in band '{band}'. Supported: {band_info.standards}")

        unsupported = [t for t in test_types if t not in band_info.tests_supported]
        if unsupported:
            raise ValueError(f"Unsupported test_types in band '{band}': {unsupported}. Supported: {band_info.tests_supported}")

        # channels policy 최소 체크
        policy = channels.get("policy")
        if policy == "CUSTOM_LIST":
            ch_list = channels.get("channels", [])
            if not ch_list:
                raise ValueError("channels.policy is CUSTOM_LIST but channels.channels is empty.")   
            
    def list_runs_for_results(self, project_id: str, limit: int = 100):
        return self.run_repo.list_recent_runs(project_id=project_id, limit=limit)


    import json

    def get_results_page(
        self,
        project_id: str,
        run_id: str,
        status_filter: str = "ALL",
        offset: int = 0,
        limit: int = 5000,
    ):
        rows = self.run_repo.list_results(
            project_id=project_id,
            run_id=run_id,
            status=status_filter,
            limit=limit,
        )

        out = []
        for r in rows:
            out.append({
                "result_id": r.get("result_id"),
                "status": r.get("status", ""),
                "test_type": r.get("test_type", ""),
                "band": r.get("band", ""),
                "standard": r.get("standard", ""),
                "group": r.get("group", ""),
                "channel": r.get("channel"),
                "bw_mhz": r.get("bw_mhz"),
                "margin_db": r.get("margin_db"),
                "measured_value": r.get("measured_value"),
                "limit_value": r.get("limit_value"),
                "reason": r.get("reason", ""),
                "test_key": r.get("test_key", ""),
            })
        return out

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
            
