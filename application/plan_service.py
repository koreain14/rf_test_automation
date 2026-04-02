import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from domain.models import (
    InstrumentProfile, Match, OverrideRule, Preset, Recipe, RuleSet, TestCase
)
from domain.expand import build_recipe, expand_recipe
from domain.ruleset_models import normalize_voltage_policy
from domain.overrides import apply_overrides
from infrastructure.plan_repo_sqlite import PlanRepositorySQLite
from infrastructure.run_repo_sqlite import RunRepositorySQLite
from application.migrations_preset import migrate_preset_to_latest
from application.plan_query_service import PlanQueryService
from application.test_type_symbols import (
    DEFAULT_TEST_ORDER,
    canonical_supported_test_types,
    normalize_test_type_list,
    normalize_test_type_symbol,
)
from domain.ruleset_models import BandInfo, PlanMode  # 경로는 너 프로젝트에 맞게




log = logging.getLogger(__name__)


class PlanService:
    def __init__(self, repo: PlanRepositorySQLite, run_repo: RunRepositorySQLite, ruleset_dir: Path):
        self.repo = repo
        self.run_repo = run_repo
        self.ruleset_dir = ruleset_dir
        self._ruleset_cache: Dict[str, RuleSet] = {}
        self.query_service = PlanQueryService(self)

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
            test_contracts=dict(raw.get("test_contracts", {}) or {}),
            test_labels={str(k): str(v) for k, v in (raw.get("test_labels", {}) or {}).items()},
            voltage_policy=normalize_voltage_policy(raw.get("voltage_policy") or {}),
        )

        self._ruleset_cache[ruleset_id] = rs
        return rs
    
    # ---------- Project/Preset ----------
    def list_projects(self) -> List[Dict[str, Any]]:
        return self.repo.list_projects()

    def ensure_default_project(self, name: str = "RF_Project") -> str:
        """
        프리셋을 자동 생성하지 않고, 프로젝트만 최소 1개 보장한다.
        Expansion 기반 preset만 수동 생성/Import 하는 현재 개발 방향용.
        """
        projects = self.repo.list_projects()
        if projects:
            return projects[0]["project_id"]
        return self.repo.create_project(name=name, description="Default project")

    def ensure_demo_project_and_preset(self) -> Tuple[str, str]:
        """레거시 호환용. 더 이상 데모 preset을 자동 생성하지 않는다."""
        project_id = self.ensure_default_project()
        presets = self.repo.list_presets(project_id=project_id)
        preset_id = presets[0]["preset_id"] if presets else ""
        return project_id, preset_id

    def list_presets(self, project_id: str) -> List[Dict[str, Any]]:
        return self.repo.list_presets(project_id=project_id)

   
    def load_override_objs(self, preset_id: str) -> List[OverrideRule]:
        rows = self.repo.list_overrides(preset_id=preset_id)
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

        selection = dict(preset.selection or {})
        log.info(
            "build_recipe_from_preset | preset_id=%s preset_name=%s ruleset=%s shared_profile=%s per_test_profiles=%s source=db:preset_json",
            preset_id,
            preset.name,
            preset.ruleset_id,
            selection.get("measurement_profile_name", ""),
            selection.get("instrument_profile_by_test", {}),
        )
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

        search_text = str(filter_.get("search_text", "") or "").strip().lower()
        filter_test_type = normalize_test_type_symbol(filter_.get("test_type", ""))
        channel_from = filter_.get("channel_from")
        channel_to = filter_.get("channel_to")
        channel_exact = filter_.get("channel")
        bw_val = filter_.get("bw_mhz", filter_.get("bandwidth_mhz"))

        for c in cases:
            ok = True
            if filter_test_type and c.test_type != filter_test_type:
                ok = False
            if "band" in filter_ and filter_["band"] and c.band != filter_["band"]:
                ok = False
            if "standard" in filter_ and filter_["standard"] and c.standard != filter_["standard"]:
                ok = False
            if bw_val not in (None, "") and c.bw_mhz != int(bw_val):
                ok = False
            if channel_exact not in (None, "") and c.channel != int(channel_exact):
                ok = False
            if channel_from not in (None, "") and c.channel < int(channel_from):
                ok = False
            if channel_to not in (None, "") and c.channel > int(channel_to):
                ok = False
            if "phy_mode" in filter_ and filter_["phy_mode"]:
                if str(c.tags.get("phy_mode", "")) != str(filter_["phy_mode"]):
                    ok = False
            if search_text:
                hay = " ".join([
                    str(c.test_type), str(c.band), str(c.standard), str(c.channel),
                    str(c.center_freq_mhz), str(c.bw_mhz), str(c.key),
                    str(c.tags.get("group", "")), str(c.tags.get("phy_mode", "")),
                ]).lower()
                if search_text not in hay:
                    ok = False
            if ok:
                yield c
                
    def summarize_cases(
        self,
        ruleset: RuleSet,
        recipe: Recipe,
        overrides: List[OverrideRule],
        filter_: Optional[Dict[str, Any]] = None,
    ):
        return self.query_service.summarize_cases(ruleset, recipe, overrides, filter_)

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
        base = self.repo.load_preset(preset_id=base_preset_id)
        failed = self.run_repo.get_failed_cases(project_id=project_id, run_id=run_id)

        if not failed:
            raise ValueError("No FAIL cases found in this run.")

        # 실패 케이스에서 필요한 최소 정보만 모아서 re-run selection 구성
        test_types = normalize_test_type_list(sorted({r["test_type"] for r in failed}))
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

        base = self.repo.load_preset(preset_id=base_preset_id)

        # base preset이 신포맷이면 selection을 복사, 구포맷이면 base 자체를 selection으로 취급
        if "selection" in base:
            selection = dict(base["selection"])
        else:
            selection = dict(base)

        # 선택된 row에서 필요한 값들 집계
        test_types = normalize_test_type_list(sorted({r["test_type"] for r in selected_rows if r.get("test_type")}))
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
        pj = self.repo.load_preset(preset_id=preset_id)

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
            "test_order": normalize_test_type_list(test_order) or list(DEFAULT_TEST_ORDER),
            "include_bw_in_group": True
        }

        self.repo.update_preset_json(preset_id=preset_id, preset_json=pj)
        
    def load_preset_obj(self, preset_id: str) -> Preset:
        pj = self.repo.load_preset(preset_id=preset_id)

        migrated, changed = migrate_preset_to_latest(pj)

        # ✅ 옵션: 개발 중에는 최신으로 자동 저장해 DB를 깨끗하게 유지
        if changed:
            self.repo.update_preset_json(preset_id=preset_id, preset_json=migrated)

        selection = dict(migrated.get("selection") or {})
        log.info(
            "load_preset_obj | preset_id=%s preset_name=%s ruleset=%s shared_profile=%s per_test_profiles=%s source=db:preset_json migrated=%s",
            preset_id,
            migrated.get("name", ""),
            migrated.get("ruleset_id", ""),
            selection.get("measurement_profile_name", ""),
            selection.get("instrument_profile_by_test", {}),
            changed,
        )
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
        test_types = normalize_test_type_list(sel.get("test_types", []))
        channels = sel.get("channels", {})
        wlan = sel.get("wlan_expansion") or {}

        if band not in ruleset.bands:
            raise ValueError(f"Band '{band}' is not defined in RuleSet. Available: {list(ruleset.bands.keys())}")

        band_info = ruleset.bands[band]

        mode_plan = list(wlan.get("mode_plan") or [])
        if mode_plan:
            standards = []
            for item in mode_plan:
                standard = str(item.get("standard", item.get("mode", ""))).strip()
                if not standard:
                    raise ValueError("wlan_expansion.mode_plan includes an empty standard.")
                if standard not in standards:
                    standards.append(standard)
            unsupported_standards = [s for s in standards if s not in band_info.standards]
            if unsupported_standards:
                raise ValueError(
                    f"Unsupported standards in WLAN expansion for band '{band}': {unsupported_standards}. Supported: {band_info.standards}"
                )
        else:
            standard = sel.get("standard")
            if standard not in band_info.standards:
                raise ValueError(f"Standard '{standard}' not supported in band '{band}'. Supported: {band_info.standards}")

        supported_keys = set(canonical_supported_test_types(band_info.tests_supported))
        unsupported = []
        for t in test_types:
            ts = normalize_test_type_symbol(t)
            if ts in supported_keys:
                continue
            unsupported.append(t)
        if unsupported:
            raise ValueError(f"Unsupported test_types in band '{band}': {unsupported}. Supported: {band_info.tests_supported}")

        if wlan:
            channel_plan = list(wlan.get("channel_plan") or [])
            if not channel_plan:
                raise ValueError("wlan_expansion.channel_plan is empty.")
            for item in channel_plan:
                ch_list = item.get("channels", [])
                if not ch_list:
                    raise ValueError("wlan_expansion.channel_plan contains an empty channels list.")
        else:
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
                "test_type": normalize_test_type_symbol(r.get("test_type", "")),
                "band": r.get("band", ""),
                "standard": r.get("standard", ""),
                "group": r.get("group", ""),
                "channel": r.get("channel"),
                "bw_mhz": r.get("bw_mhz"),
                "margin_db": r.get("margin_db"),
                "difference_value": r.get("difference_value"),
                "difference_unit": r.get("difference_unit", ""),
                "comparator": r.get("comparator", ""),
                "measurement_unit": r.get("measurement_unit", ""),
                "measurement_method": r.get("measurement_method", ""),
                "measurement_profile_name": r.get("measurement_profile_name", ""),
                "measurement_profile_source": r.get("measurement_profile_source", ""),
                "measured_value": r.get("measured_value"),
                "limit_value": r.get("limit_value"),
                "screenshot_path": r.get("screenshot_path", ""),
                "screenshot_abs_path": r.get("screenshot_abs_path", ""),
                "has_screenshot": bool(r.get("has_screenshot")),
                "voltage_condition": r.get("voltage_condition", ""),
                "nominal_voltage_v": r.get("nominal_voltage_v"),
                "target_voltage_v": r.get("target_voltage_v"),
                "last_step_data": dict(r.get("last_step_data") or {}),
                "reason": r.get("reason", ""),
                "test_key": r.get("test_key", ""),
            })
        return out

    def get_comparable_results(self, project_id: str, run_a: str, run_b: str) -> List[Dict[str, Any]]:
        rows_a = self.get_results_page(project_id=project_id, run_id=run_a, status_filter="ALL", offset=0, limit=5000)
        rows_b = self.get_results_page(project_id=project_id, run_id=run_b, status_filter="ALL", offset=0, limit=5000)

        def make_key(r: Dict[str, Any]):
            return (
                str(r.get("test_key", "")),
                str(r.get("test_type", "")),
                str(r.get("band", "")),
                str(r.get("standard", "")),
                str(r.get("channel", "")),
                str(r.get("bw_mhz", "")),
                str(r.get("voltage_condition", "")),
                str(r.get("target_voltage_v", "")),
            )

        map_a = {make_key(r): r for r in rows_a}
        map_b = {make_key(r): r for r in rows_b}

        out: List[Dict[str, Any]] = []
        for key in sorted(set(map_a.keys()) | set(map_b.keys())):
            a = map_a.get(key, {})
            b = map_b.get(key, {})
            margin_a = a.get("margin_db")
            margin_b = b.get("margin_db")
            difference_a = a.get("difference_value")
            difference_b = b.get("difference_value")
            measured_a = a.get("measured_value")
            measured_b = b.get("measured_value")
            difference_unit_a = str(a.get("difference_unit", "") or "")
            difference_unit_b = str(b.get("difference_unit", "") or "")
            measured_unit_a = str(a.get("measurement_unit", "") or difference_unit_a)
            measured_unit_b = str(b.get("measurement_unit", "") or difference_unit_b)
            if difference_unit_a and difference_unit_b and difference_unit_a == difference_unit_b:
                try:
                    delta_difference = round(float(difference_b) - float(difference_a), 3)
                except Exception:
                    delta_difference = ""
                delta_difference_unit = difference_unit_a
            else:
                delta_difference = ""
                delta_difference_unit = ""
            if measured_unit_a and measured_unit_b and measured_unit_a == measured_unit_b:
                try:
                    delta_value = round(float(measured_b) - float(measured_a), 3)
                except Exception:
                    delta_value = ""
                delta_unit = measured_unit_a
            else:
                delta_value = ""
                delta_unit = ""

            status_a = a.get("status", "MISSING") if a else "MISSING"
            status_b = b.get("status", "MISSING") if b else "MISSING"

            out.append({
                "test_key": key[0],
                "test_type": key[1],
                "band": key[2],
                "standard": key[3],
                "channel": key[4],
                "bw_mhz": key[5],
                "voltage_condition": key[6],
                "status_a": status_a,
                "status_b": status_b,
                "margin_a": "" if margin_a is None else margin_a,
                "margin_b": "" if margin_b is None else margin_b,
                "difference_a": "" if difference_a is None else difference_a,
                "difference_b": "" if difference_b is None else difference_b,
                "difference_unit": difference_unit_a or difference_unit_b,
                "measured_a": "" if measured_a is None else measured_a,
                "measured_b": "" if measured_b is None else measured_b,
                "unit": measured_unit_a or measured_unit_b or difference_unit_a or difference_unit_b,
                "delta_value": delta_value,
                "delta_unit": delta_unit,
                "delta_difference": delta_difference,
                "delta_difference_unit": delta_difference_unit,
                "limit_a": a.get("limit_value", ""),
                "limit_b": b.get("limit_value", ""),
                "comparator_a": a.get("comparator", ""),
                "comparator_b": b.get("comparator", ""),
                "screenshot_path_a": a.get("screenshot_path", ""),
                "screenshot_path_b": b.get("screenshot_path", ""),
                "screenshot_abs_path_a": a.get("screenshot_abs_path", ""),
                "screenshot_abs_path_b": b.get("screenshot_abs_path", ""),
                "has_screenshot_a": bool(a.get("has_screenshot")),
                "has_screenshot_b": bool(b.get("has_screenshot")),
                "voltage_condition": a.get("voltage_condition") or b.get("voltage_condition") or "",
                "nominal_voltage_v_a": a.get("nominal_voltage_v"),
                "nominal_voltage_v_b": b.get("nominal_voltage_v"),
                "target_voltage_v_a": a.get("target_voltage_v"),
                "target_voltage_v_b": b.get("target_voltage_v"),
                "target_voltage_v_display_a": a.get("target_voltage_v"),
                "target_voltage_v_display_b": b.get("target_voltage_v"),
                "changed": (
                    (status_a != status_b)
                    or (delta_value != "" and delta_value != 0)
                    or (delta_difference != "" and delta_difference != 0)
                ),
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
            
