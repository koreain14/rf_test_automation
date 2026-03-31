from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from application.measurement_profile_loader import MeasurementProfileLoader
from application.test_type_symbols import normalize_profile_name
from application.test_type_symbols import default_profile_for_test_type
from application.test_type_symbols import normalize_test_type_symbol


log = logging.getLogger(__name__)


class InstrumentProfileResolver:
    """Resolves logical profile names like PSD_DEFAULT into concrete analyzer settings.

    Public API stays unchanged while internal resolution prefers MeasurementProfileLoader.
    Legacy DEFAULTS remain as a compatibility fallback because current execution paths
    still generate names like PSD_DEFAULT / OBW_DEFAULT / SP_DEFAULT / TXP_DEFAULT.
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
        self.loader = MeasurementProfileLoader(self._resolve_profiles_dir(self.config_path))

    def resolve(self, profile_name: str | None) -> Dict[str, Any]:
        name = normalize_profile_name(profile_name)
        if not name:
            return {}

        test_type = self._infer_test_type(name)
        if test_type:
            resolved = self.resolve_for_test_type(name, test_type)
            if resolved:
                return resolved

        resolved = self._resolve_profile_common(name)
        if resolved:
            resolved["profile_name"] = name
            resolved.setdefault("profile_source", "loader_profile")
            return resolved

        resolved = dict(self.DEFAULTS.get(name, {}))
        resolved["profile_name"] = name
        if test_type:
            resolved["test_type"] = test_type
        resolved["profile_source"] = "compat_defaults"
        resolved["measurement_field_sources"] = {
            str(k): "inherited_default"
            for k in resolved.keys()
            if str(k) not in {"profile_name", "test_type", "profile_source", "measurement_field_sources"}
        }
        return resolved

    def resolve_for_analyzer(self, profile_name: str | None, analyzer_model: str | None) -> Dict[str, Any]:
        resolved = self.resolve(profile_name)
        resolved["analyzer_model"] = str(analyzer_model or "")
        # future model-aware normalization hook
        return resolved

    def resolve_for_test_type(self, profile_name: str | None, test_type: str | None) -> Dict[str, Any]:
        name = normalize_profile_name(profile_name)
        normalized_test_type = normalize_test_type_symbol(test_type)
        if not name or not normalized_test_type:
            return {}

        resolved = self._resolve_measurement_via_loader(name, normalized_test_type)
        if resolved:
            resolved["profile_name"] = str(resolved.get("profile_name") or name)
            resolved["test_type"] = str(resolved.get("test_type") or normalized_test_type)
            resolved.setdefault("profile_source", "loader_measurement")
            return resolved

        fallback_profile_name = normalize_profile_name(default_profile_for_test_type(normalized_test_type))
        if fallback_profile_name and fallback_profile_name != name:
            resolved = self._resolve_measurement_via_loader(fallback_profile_name, normalized_test_type)
            if resolved:
                resolved["profile_name"] = str(resolved.get("profile_name") or fallback_profile_name)
                resolved["test_type"] = str(resolved.get("test_type") or normalized_test_type)
                resolved["profile_source"] = "loader_default_for_test_type"
                resolved["requested_profile_name"] = name
                return resolved

        compat_name = self._compat_default_name(name, normalized_test_type)
        resolved = dict(self.DEFAULTS.get(compat_name, {}))
        if not resolved:
            return {}
        resolved["profile_name"] = compat_name
        resolved["test_type"] = normalized_test_type
        resolved["profile_source"] = "compat_defaults"
        resolved["measurement_field_sources"] = {
            str(k): "inherited_default"
            for k in resolved.keys()
            if str(k) not in {"profile_name", "test_type", "profile_source", "requested_profile_name", "measurement_field_sources"}
        }
        if compat_name != name:
            resolved["requested_profile_name"] = name
        return resolved

    def _resolve_measurement_via_loader(self, profile_name: str, test_type: str) -> Dict[str, Any]:
        try:
            resolved = self.loader.resolve_measurement(profile_name, test_type)
            return self._filter_loader_result(resolved)
        except FileNotFoundError:
            log.debug("measurement profile file path not found | profile=%s", profile_name, exc_info=True)
        except KeyError:
            log.debug("measurement profile not found in loader | profile=%s test_type=%s", profile_name, test_type, exc_info=True)
        except ValueError:
            log.warning("measurement profile resolution failed | profile=%s test_type=%s", profile_name, test_type, exc_info=True)
        except Exception:
            log.warning("unexpected measurement profile resolution error | profile=%s test_type=%s", profile_name, test_type, exc_info=True)
        return {}

    def _resolve_profile_common(self, profile_name: str) -> Dict[str, Any]:
        try:
            resolved = self.loader.resolve_profile(profile_name)
            common = dict(resolved.get("common") or {})
            common["profile_name"] = str(resolved.get("name") or profile_name)
            return self._filter_loader_result(common)
        except FileNotFoundError:
            log.debug("measurement profile file path not found | profile=%s", profile_name, exc_info=True)
        except KeyError:
            log.debug("measurement profile common payload not found in loader | profile=%s", profile_name, exc_info=True)
        except ValueError:
            log.warning("measurement profile common resolution failed | profile=%s", profile_name, exc_info=True)
        except Exception:
            log.warning("unexpected measurement profile common resolution error | profile=%s", profile_name, exc_info=True)
        return {}

    def _infer_test_type(self, profile_name: str) -> str:
        normalized = normalize_profile_name(profile_name)
        if not normalized:
            return ""

        mapping = {
            "PSD_DEFAULT": "PSD",
            "OBW_DEFAULT": "OBW",
            "SP_DEFAULT": "SP",
            "TXP_DEFAULT": "CHANNEL_POWER",
        }
        if normalized in mapping:
            return mapping[normalized]

        prefix = normalized.split("_", 1)[0]
        return normalize_test_type_symbol(prefix)

    def _compat_default_name(self, profile_name: str, test_type: str) -> str:
        normalized = normalize_profile_name(profile_name)
        if normalized in self.DEFAULTS:
            return normalized
        fallback = normalize_profile_name(default_profile_for_test_type(test_type))
        if fallback in self.DEFAULTS:
            return fallback
        return normalized

    def _filter_loader_result(self, resolved: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            "span_hz",
            "rbw_hz",
            "vbw_hz",
            "ref_level_dbm",
            "trace_mode",
            "detector",
            "sweep_time_s",
            "sweep_time_ms",
            "sweep_auto",
            "avg_count",
            "average_enabled",
            "average",
            "att_db",
            "atten_db",
            "profile_name",
            "test_type",
            "requested_profile_name",
            "profile_source",
            "measurement_field_sources",
        }
        return {str(k): v for k, v in dict(resolved or {}).items() if str(k) in allowed}

    def _resolve_profiles_dir(self, config_path: Path) -> Path:
        if config_path.is_dir():
            return config_path
        if config_path.name == "equipment_profiles.json":
            return config_path.parent / "measurement_profiles"
        return config_path.parent / "measurement_profiles"
