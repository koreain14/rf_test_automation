from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Dict, List, Optional

from application.migrations_preset import migrate_preset_to_latest
from application.preset_migration import build_effective_preset, summarize_migration_result
from application.test_type_symbols import canonical_supported_test_types, normalize_test_type_list, normalize_test_type_symbol
from domain.expand import build_recipe, expand_recipe
from domain.models import Match, OverrideRule, Preset, Recipe, RuleSet, TestCase
from domain.overrides import apply_overrides

log = logging.getLogger(__name__)


class PresetBuildService:
    def __init__(self, owner):
        self.owner = owner

    @property
    def repo(self):
        return self.owner.repo

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

    def build_recipe_from_preset(self, preset_id: str):
        raw_preset = self.load_preset_obj(preset_id)
        if raw_preset is None:
            raise KeyError(f"Preset not found: {preset_id}")

        preset = raw_preset
        migration = None
        ruleset = self.owner.load_ruleset(preset.ruleset_id)

        effective = build_effective_preset(raw_preset, ruleset)
        migration = effective.migration
        self.validate_preset_against_ruleset(preset, ruleset)

        if migration.has_blocking_errors:
            raise ValueError(
                "Preset is invalid against the current RuleSet.\n" + summarize_migration_result(migration)
            )

        selection = dict(preset.selection or {})
        log.info(
            "build_recipe_from_preset | preset_id=%s preset_name=%s ruleset=%s shared_profile=%s per_test_profiles=%s source=db:preset_json migration=%s",
            preset_id,
            preset.name,
            preset.ruleset_id,
            selection.get("measurement_profile_name", ""),
            selection.get("instrument_profile_by_test", {}),
            summarize_migration_result(migration) if migration is not None else "status=clean",
        )
        recipe = build_recipe(ruleset, effective.effective_preset)
        recipe = replace(
            recipe,
            meta={
                **dict(recipe.meta or {}),
                "preset_migration_status": migration.status if migration is not None else "clean",
                "preset_migration_auto_fixes": list(migration.auto_fixes) if migration is not None else [],
                "preset_migration_warnings": list(migration.warnings) if migration is not None else [],
                "preset_migration_disabled_items": [
                    {"field": item.field, "value": item.value, "reason": item.reason}
                    for item in (migration.disabled_items if migration is not None else [])
                ],
                "preset_migration_errors": list(migration.errors) if migration is not None else [],
                "effective_test_types": normalize_test_type_list(
                    (effective.effective_preset.selection or {}).get("test_types") or []
                ),
                "raw_test_types": normalize_test_type_list((raw_preset.selection or {}).get("test_types") or []),
            },
        )
        overrides = self.load_override_objs(preset_id) or []
        return ruleset, raw_preset, recipe, overrides

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

    def count_cases(self, ruleset, recipe, overrides, filter_=None) -> int:
        count = 0
        for _ in self.iter_cases(ruleset=ruleset, recipe=recipe, overrides=overrides, filter_=filter_):
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

    def load_preset_obj(self, preset_id: str) -> Preset:
        pj = self.repo.load_preset(preset_id=preset_id)
        migrated, changed = migrate_preset_to_latest(pj)
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
            raise ValueError(
                f"Unsupported test types for band '{band}': {unsupported}. Supported: {sorted(supported_keys)}"
            )

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
