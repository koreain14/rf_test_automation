from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_INSTRUMENT_SETTINGS: Dict[str, Any] = {
    "mode": "AUTO",          # AUTO / DUMMY / SCPI
    "resource_name": "",
    "timeout_ms": 10000,
}


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def load_instrument_settings(self) -> Dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULT_INSTRUMENT_SETTINGS)

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return dict(DEFAULT_INSTRUMENT_SETTINGS)

        settings = dict(DEFAULT_INSTRUMENT_SETTINGS)
        if isinstance(raw, dict):
            settings.update(raw.get("instrument", raw))
        return settings

    def save_instrument_settings(self, settings: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"instrument": settings}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
