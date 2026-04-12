from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

from application.correction_profile_model import CorrectionFactorSet, CorrectionProfileDocument


_ALLOWED_MODES = {"DIRECT", "SWITCH"}


class CorrectionProfileLoader:
    def __init__(self, path: str | Path = "config/correction_profiles.json"):
        self.path = Path(path)

    def _read_json(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"profiles": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"profiles": []}
        except Exception:
            return {"profiles": []}

    def list_profiles(self) -> List[CorrectionProfileDocument]:
        raw = self._read_json()
        out: List[CorrectionProfileDocument] = []
        for item in raw.get("profiles", []):
            if not isinstance(item, dict):
                continue
            try:
                out.append(CorrectionProfileDocument.from_dict(item, source_path=self.path))
            except Exception:
                continue
        return out

    def get_profile(self, name: str) -> Optional[CorrectionProfileDocument]:
        target = str(name or "").strip()
        if not target:
            return None
        for profile in self.list_profiles():
            if profile.name == target:
                return profile
        return None

    def resolve_effective_factors(
        self,
        profile_name: str,
        mode: str | None = None,
        rf_path: str | None = None,
    ) -> dict[str, Any]:
        profile = self.get_profile(profile_name)
        requested_mode = str(mode or "").strip().upper()
        bound_path = str(rf_path or "").strip()

        if profile is None:
            return {
                "ok": False,
                "reason": "PROFILE_NOT_FOUND",
                "profile_name": str(profile_name or "").strip(),
                "requested_mode": requested_mode,
                "resolved_mode": "",
                "rf_path": bound_path,
                "bound_port": "",
                "factors": {},
                "available_ports": [],
                "message": "Requested correction profile was not found.",
            }

        resolved_mode = requested_mode if requested_mode in _ALLOWED_MODES else profile.normalized_mode()

        if resolved_mode == "DIRECT":
            return {
                "ok": True,
                "reason": "OK",
                "profile_name": profile.name,
                "requested_mode": requested_mode,
                "resolved_mode": "DIRECT",
                "rf_path": bound_path,
                "bound_port": "DIRECT",
                "factors": profile.factors.to_dict(),
                "available_ports": [],
                "message": "",
            }

        ports = dict(profile.ports or {})
        available_ports = sorted(str(name or "").strip() for name in ports.keys() if str(name or "").strip())

        if not bound_path:
            return {
                "ok": False,
                "reason": "RF_PATH_MISSING",
                "profile_name": profile.name,
                "requested_mode": requested_mode,
                "resolved_mode": "SWITCH",
                "rf_path": "",
                "bound_port": "",
                "factors": {},
                "available_ports": available_ports,
                "message": "SWITCH profile requires an RF path string to resolve effective factors.",
            }

        factor_set = ports.get(bound_path)
        if factor_set is None:
            return {
                "ok": False,
                "reason": "PORT_NOT_FOUND",
                "profile_name": profile.name,
                "requested_mode": requested_mode,
                "resolved_mode": "SWITCH",
                "rf_path": bound_path,
                "bound_port": "",
                "factors": {},
                "available_ports": available_ports,
                "message": f"RF path '{bound_path}' is not present in the SWITCH profile.",
            }

        if not isinstance(factor_set, CorrectionFactorSet):
            try:
                factor_set = CorrectionFactorSet.from_dict(dict(factor_set or {}))
            except Exception:
                factor_set = CorrectionFactorSet()

        return {
            "ok": True,
            "reason": "OK",
            "profile_name": profile.name,
            "requested_mode": requested_mode,
            "resolved_mode": "SWITCH",
            "rf_path": bound_path,
            "bound_port": bound_path,
            "factors": factor_set.to_dict(),
            "available_ports": available_ports,
            "message": "",
        }


__all__ = ["CorrectionProfileLoader"]
