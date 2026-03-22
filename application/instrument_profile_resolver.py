from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class InstrumentProfileResolver:
    """Resolves logical profile names like PSD_DEFAULT into concrete analyzer settings.

    This version intentionally stays read-only and non-invasive so current run flow is not broken.
    """

    DEFAULTS: Dict[str, Dict[str, Any]] = {
        "PSD_DEFAULT": {
            "span_hz": 100_000_000,
            "rbw_hz": 100_000,
            "vbw_hz": 300_000,
            "ref_level_dbm": 20,
            "trace_mode": "AVERAGE",
            "detector": "RMS",
        },
        "OBW_DEFAULT": {
            "span_hz": 100_000_000,
            "rbw_hz": 100_000,
            "vbw_hz": 300_000,
            "ref_level_dbm": 20,
            "trace_mode": "CLEAR_WRITE",
            "detector": "POSITIVE",
        },
        "SP_DEFAULT": {
            "span_hz": 1_000_000_000,
            "rbw_hz": 1_000_000,
            "vbw_hz": 3_000_000,
            "ref_level_dbm": 20,
            "trace_mode": "MAX_HOLD",
            "detector": "POSITIVE",
        },
        "TXP_DEFAULT": {
            "span_hz": 100_000_000,
            "rbw_hz": 100_000,
            "vbw_hz": 300_000,
            "ref_level_dbm": 20,
            "trace_mode": "CLEAR_WRITE",
            "detector": "RMS",
        },
    }

    def __init__(self, config_path: str | Path = "config/equipment_profiles.json"):
        self.config_path = Path(config_path)

    def resolve(self, profile_name: str | None) -> Dict[str, Any]:
        name = str(profile_name or "").strip()
        if not name:
            return {}
        resolved = dict(self.DEFAULTS.get(name, {}))
        resolved["profile_name"] = name
        return resolved

    def resolve_for_analyzer(self, profile_name: str | None, analyzer_model: str | None) -> Dict[str, Any]:
        resolved = self.resolve(profile_name)
        resolved["analyzer_model"] = str(analyzer_model or "")
        # future model-aware normalization hook
        return resolved
