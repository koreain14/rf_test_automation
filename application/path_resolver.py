from __future__ import annotations

from typing import Any, Dict


class PathResolver:
    """Small compatibility layer for switch-path resolution.

    Current project stores an RF path in recipe.meta.rf_path.switch_path.
    This resolver normalizes it into a dict so future switch drivers can consume it.
    """

    def resolve(self, recipe_meta: Dict[str, Any] | None) -> Dict[str, Any]:
        meta = recipe_meta or {}
        rf_path = meta.get("rf_path") or {}
        switch_path = rf_path.get("switch_path")
        return {
            "switch_path": str(switch_path or "").strip(),
            "rf_path": dict(rf_path) if isinstance(rf_path, dict) else {},
        }
