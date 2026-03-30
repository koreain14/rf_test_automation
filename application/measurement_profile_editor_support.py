from __future__ import annotations

from copy import deepcopy
from typing import Any

from application.measurement_profile_loader import MeasurementProfileLoader
from application.measurement_profile_model import MeasurementProfileDocument
from application.test_type_symbols import CANONICAL_TEST_TYPES
from application.test_type_symbols import normalize_profile_name


COMMON_FIELD_SPECS: list[dict[str, str]] = [
    {"key": "ref_level_dbm", "label": "Ref Level (dBm)", "kind": "float"},
    {"key": "sweep_time_s", "label": "Sweep Time (s)", "kind": "float"},
    {"key": "avg_count", "label": "Average Count", "kind": "int"},
    {"key": "att_db", "label": "Attenuation (dB)", "kind": "float"},
]


MEASUREMENT_FIELD_SPECS: list[dict[str, Any]] = [
    {"key": "span_hz", "label": "Span (MHz)", "kind": "float", "display_unit": "mhz"},
    {"key": "rbw_hz", "label": "RBW (MHz)", "kind": "float", "display_unit": "mhz"},
    {"key": "vbw_hz", "label": "VBW (MHz)", "kind": "float", "display_unit": "mhz"},
    {"key": "detector", "label": "Detector", "kind": "choice"},
    {"key": "trace_mode", "label": "Trace Mode", "kind": "choice"},
    {"key": "ref_level_dbm", "label": "Ref Level (dBm)", "kind": "float"},
    {"key": "sweep_time_s", "label": "Sweep Time (s)", "kind": "float"},
    {"key": "avg_count", "label": "Average Count", "kind": "int"},
    {"key": "att_db", "label": "Attenuation (dB)", "kind": "float"},
]


CHOICE_OPTIONS: dict[str, list[str]] = {
    "detector": ["PEAK", "POSITIVE", "RMS", "AVERAGE", "SAMPLE", "NEGATIVE"],
    "trace_mode": ["CLEAR_WRITE", "MAX_HOLD", "AVERAGE"],
}


def clone_document(doc: MeasurementProfileDocument | None) -> MeasurementProfileDocument:
    if doc is None:
        return MeasurementProfileDocument(name="", version=1)
    return MeasurementProfileDocument.from_dict(doc.to_dict(), source_path=doc.source_path)


def default_editor_document(loader: MeasurementProfileLoader) -> MeasurementProfileDocument:
    return MeasurementProfileDocument(
        name="",
        version=1,
        base="default" if loader.get_profile_document("default") is not None else None,
        description="",
        common={},
        measurements={},
        meta={},
    )


def effective_base_name(loader: MeasurementProfileLoader, document: MeasurementProfileDocument) -> str:
    if document.base:
        return normalize_profile_name(document.base)
    if normalize_profile_name(document.name) != "default" and loader.get_profile_document("default") is not None:
        return "default"
    return ""


def resolved_base_profile(loader: MeasurementProfileLoader, document: MeasurementProfileDocument) -> dict[str, Any]:
    base_name = effective_base_name(loader, document)
    if not base_name:
        return {"common": {}, "measurements": {}}
    return dict(loader.resolve_profile(base_name) or {})


def cycle_forbidden_base_names(loader: MeasurementProfileLoader, profile_name: str) -> set[str]:
    target = normalize_profile_name(profile_name)
    if not target:
        return set()

    docs = loader.load_profile_map()
    forbidden = {target}
    changed = True
    while changed:
        changed = False
        for name, doc in docs.items():
            base_name = normalize_profile_name(doc.base)
            if base_name in forbidden and name not in forbidden:
                forbidden.add(name)
                changed = True
    return forbidden


def build_override_document(
    *,
    loader: MeasurementProfileLoader,
    original_document: MeasurementProfileDocument | None,
    name: str,
    base: str | None,
    description: str,
    common_values: dict[str, Any],
    measurement_values: dict[str, dict[str, Any]],
) -> MeasurementProfileDocument:
    clean_name = str(name or "").strip()
    clean_base = normalize_profile_name(base)
    if not clean_name:
        raise ValueError("Profile name is required.")
    if clean_base and normalize_profile_name(clean_name) == clean_base:
        raise ValueError("Measurement profile cannot reference itself as base.")

    base_resolved = dict(loader.resolve_profile(clean_base) or {}) if clean_base else {"common": {}, "measurements": {}}
    base_common = dict(base_resolved.get("common") or {})
    base_measurements = dict(base_resolved.get("measurements") or {})

    raw_common = _diff_section(common_values, base_common)
    raw_measurements: dict[str, dict[str, Any]] = {}
    for test_type in CANONICAL_TEST_TYPES:
        current_section = dict(measurement_values.get(test_type) or {})
        base_section = dict(base_measurements.get(test_type) or {})
        diff = _diff_section(current_section, base_section)
        if diff:
            raw_measurements[test_type] = diff

    meta = deepcopy(dict(getattr(original_document, "meta", {}) or {}))
    source_path = getattr(original_document, "source_path", None)
    version = int(getattr(original_document, "version", 1) or 1)

    return MeasurementProfileDocument(
        name=clean_name,
        version=version,
        base=clean_base or None,
        description=str(description or "").strip(),
        common=raw_common,
        measurements=raw_measurements,
        meta=meta,
        source_path=source_path,
    )


def _diff_section(current: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    keys = set(dict(current or {}).keys())
    for key in keys:
        current_value = current.get(key)
        if current_value in (None, ""):
            continue
        if _values_equal(current_value, base.get(key)):
            continue
        out[str(key)] = deepcopy(current_value)
    return out


def _values_equal(left: Any, right: Any) -> bool:
    if left in (None, "") and right in (None, ""):
        return True
    try:
        if isinstance(left, (int, float)) or isinstance(right, (int, float)):
            return float(left) == float(right)
    except Exception:
        pass
    return left == right
