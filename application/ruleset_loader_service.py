from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from domain.models import InstrumentProfile, RuleSet
from domain.ruleset_models import (
    BandInfo,
    PlanMode,
    collect_ruleset_test_types,
    normalize_case_dimensions,
    normalize_data_rate_policy,
    normalize_instrument_profile_refs,
    normalize_voltage_policy,
    project_ruleset_test_contracts,
)


class RuleSetLoaderService:
    def __init__(self, *, ruleset_dir: Path, cache: Dict[str, RuleSet]):
        self.ruleset_dir = ruleset_dir
        self.cache = cache

    def load_ruleset(self, ruleset_id: str) -> RuleSet:
        if ruleset_id in self.cache:
            return self.cache[ruleset_id]

        path = self.ruleset_dir / f"{ruleset_id.lower()}.json"
        if not path.exists():
            alt = self.ruleset_dir / "kc_wlan.json"
            if alt.exists() and ruleset_id == "KC_WLAN":
                path = alt
            else:
                raise FileNotFoundError(f"RuleSet json not found for {ruleset_id}")

        raw = json.loads(path.read_text(encoding="utf-8"))
        instrument_profiles = {
            name: InstrumentProfile(name=name, settings=settings)
            for name, settings in (raw.get("instrument_profiles", {}) or {}).items()
        }
        bands_raw: Dict[str, dict] = raw.get("bands", {}) or {}
        bands = {band_name: BandInfo.from_dict(band_name, band_dict) for band_name, band_dict in bands_raw.items()}
        plan_modes_raw: Dict[str, dict] = raw.get("plan_modes", {}) or {}
        plan_modes = {mode_name: PlanMode.from_dict(mode_name, mode_dict) for mode_name, mode_dict in plan_modes_raw.items()}

        ruleset = RuleSet(
            id=raw["id"],
            version=raw.get("version", ""),
            regulation=raw.get("regulation", ""),
            tech=raw.get("tech", ""),
            bands=bands,
            schema_version=int(raw.get("schema_version", 1) or 1),
            instrument_profiles=instrument_profiles,
            instrument_profile_refs=normalize_instrument_profile_refs(
                raw.get("instrument_profile_refs") or {},
                test_contracts=raw.get("test_contracts") or {},
            ),
            plan_modes=plan_modes,
            test_contracts=project_ruleset_test_contracts(
                raw.get("test_contracts") or {},
                tests_supported=collect_ruleset_test_types(raw),
            ),
            test_labels={str(k): str(v) for k, v in (raw.get("test_labels", {}) or {}).items()},
            voltage_policy=normalize_voltage_policy(raw.get("voltage_policy") or {}),
            data_rate_policy=normalize_data_rate_policy(raw.get("data_rate_policy") or {}),
            case_dimensions=normalize_case_dimensions(raw.get("case_dimensions") or {}),
        )
        self.cache[ruleset_id] = ruleset
        return ruleset
