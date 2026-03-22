from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from domain.models import OverrideRule, Preset, Recipe, RuleSet, TestCase


@dataclass
class PlanContext:
    project_id: str
    preset_id: str
    ruleset: RuleSet
    preset: Preset
    recipe: Recipe
    overrides: List[OverrideRule]
    all_cases: List[TestCase] = field(default_factory=list)
    case_enabled: Dict[str, bool] = field(default_factory=dict)
    case_order: List[str] = field(default_factory=list)
    deleted_case_keys: Set[str] = field(default_factory=set)
    case_excluded: Set[str] = field(default_factory=set)
    case_priority_tags: Dict[str, str] = field(default_factory=dict)
