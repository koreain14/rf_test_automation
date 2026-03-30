from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from application.measurement_profile_model import MeasurementProfileDocument
from application.test_type_symbols import normalize_profile_name, normalize_test_type_symbol


class MeasurementProfileLoader:
    def __init__(self, profiles_dir: str | Path = "config/measurement_profiles"):
        self.profiles_dir = Path(profiles_dir)

    def list_profiles(self) -> list[MeasurementProfileDocument]:
        return [self._load_document(path) for path in self._iter_profile_paths()]

    def get_profile_document(self, profile_name: str) -> MeasurementProfileDocument | None:
        target = normalize_profile_name(profile_name)
        if not target:
            return None
        for path in self._iter_profile_paths():
            doc = self._load_document(path)
            self._validate_document(doc)
            if normalize_profile_name(doc.name) == target:
                return doc
        return None

    def load_profile_map(self) -> dict[str, MeasurementProfileDocument]:
        docs: dict[str, MeasurementProfileDocument] = {}
        for path in self._iter_profile_paths():
            doc = self._load_document(path)
            self._validate_document(doc)
            docs[normalize_profile_name(doc.name)] = doc
        return docs

    def resolve_profile(self, profile_name: str) -> dict[str, Any]:
        docs = self.load_profile_map()
        name = normalize_profile_name(profile_name)
        if not name:
            raise ValueError("profile_name is required")
        return self._resolve_document(name=name, docs=docs, stack=[])

    def resolve_measurement(self, profile_name: str, test_type: str) -> dict[str, Any]:
        resolved = self.resolve_profile(profile_name)
        common = dict(resolved.get("common") or {})
        measurements = dict(resolved.get("measurements") or {})
        normalized_test_type = normalize_test_type_symbol(test_type)
        test_overrides = dict(measurements.get(normalized_test_type) or {})
        merged = self._deep_merge(common, test_overrides)
        merged["profile_name"] = str(resolved.get("name") or normalize_profile_name(profile_name))
        merged["test_type"] = normalized_test_type
        return merged

    def save_profile(self, document: MeasurementProfileDocument, path: str | Path | None = None) -> Path:
        self._validate_document(document)
        if document.base and normalize_profile_name(document.base) == normalize_profile_name(document.name):
            raise ValueError("Measurement profile cannot reference itself as base.")

        target = Path(path) if path else (document.source_path or (self.profiles_dir / f"{document.name}.json"))
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = document.to_dict()
        with target.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, ensure_ascii=True)
            fp.write("\n")
        return target

    def validate_payload(self, payload: dict[str, Any]) -> MeasurementProfileDocument:
        doc = MeasurementProfileDocument.from_dict(payload)
        self._validate_document(doc)
        return doc

    def _resolve_document(
        self,
        *,
        name: str,
        docs: dict[str, MeasurementProfileDocument],
        stack: list[str],
    ) -> dict[str, Any]:
        normalized_name = normalize_profile_name(name)
        if normalized_name in stack:
            chain = " -> ".join(stack + [normalized_name])
            raise ValueError(f"Measurement profile base cycle detected: {chain}")

        doc = docs.get(normalized_name)
        if doc is None:
            raise KeyError(f"Measurement profile not found: {normalized_name}")

        effective_base = normalize_profile_name(doc.base)
        if not effective_base and normalized_name != "default" and "default" in docs:
            effective_base = "default"

        base_payload: dict[str, Any] = {}
        if effective_base:
            base_payload = self._resolve_document(name=effective_base, docs=docs, stack=stack + [normalized_name])

        current_payload = doc.to_dict()
        merged = self._deep_merge(base_payload, current_payload)
        merged["name"] = doc.name
        return merged

    def _load_document(self, path: Path) -> MeasurementProfileDocument:
        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
        doc = MeasurementProfileDocument.from_dict(dict(payload or {}), source_path=path)
        if not doc.name:
            doc.name = path.stem
        return doc

    def _iter_profile_paths(self) -> list[Path]:
        if not self.profiles_dir.exists():
            return []
        return sorted(path for path in self.profiles_dir.glob("*.json") if path.is_file())

    def _validate_document(self, doc: MeasurementProfileDocument) -> None:
        if not str(doc.name or "").strip():
            raise ValueError("Measurement profile requires 'name'.")
        if int(doc.version or 0) <= 0:
            raise ValueError("Measurement profile requires positive 'version'.")
        if doc.base is not None and not str(doc.base).strip():
            raise ValueError("Measurement profile 'base' must be a non-empty string when provided.")
        if not isinstance(doc.common, dict):
            raise ValueError("Measurement profile 'common' must be an object.")
        if not isinstance(doc.measurements, dict):
            raise ValueError("Measurement profile 'measurements' must be an object.")
        if not isinstance(doc.meta, dict):
            raise ValueError("Measurement profile 'meta' must be an object.")
        for test_type, settings in doc.measurements.items():
            normalized = normalize_test_type_symbol(test_type)
            if not normalized:
                raise ValueError(f"Measurement profile has invalid test type key: {test_type!r}")
            if not isinstance(settings, dict):
                raise ValueError(f"Measurement profile measurement '{test_type}' must be an object.")

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(dict(base or {}))
        for key, value in dict(override or {}).items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result
