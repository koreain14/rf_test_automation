from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from application.preset_model import PresetModel
from application.preset_serializer import PresetSerializer


@dataclass(frozen=True)
class PresetFileInfo:
    name: str
    path: Path
    ruleset_id: str
    is_builtin: bool
    display_group: str


class PresetRepo:
    def __init__(self, root_dir: Path, custom_subdir: str = "custom"):
        self.root_dir = Path(root_dir)
        self.custom_dir = self.root_dir / custom_subdir
        self.custom_subdir = custom_subdir

    def list_builtin(self) -> list[PresetFileInfo]:
        return self._scan(is_builtin=True)

    def list_custom(self) -> list[PresetFileInfo]:
        return self._scan(is_builtin=False)

    def list_all(self) -> list[PresetFileInfo]:
        items = self.list_builtin() + self.list_custom()
        return sorted(items, key=lambda x: (x.display_group, x.name.lower()))

    def load(self, path_or_name: str | Path) -> PresetModel:
        path = self._resolve(path_or_name)
        model = PresetSerializer.load_file(path)
        model.is_builtin = not self._is_custom_path(path)
        model.source_path = str(path)
        return model

    def save(self, model: PresetModel, file_name: str | None = None) -> Path:
        safe_name = file_name or _slugify(model.name) + ".json"
        if not safe_name.lower().endswith(".json"):
            safe_name += ".json"
        path = self.custom_dir / safe_name
        PresetSerializer.save_file(model, path)
        return path

    def delete(self, path_or_name: str | Path) -> None:
        path = self._resolve(path_or_name)
        if not self._is_custom_path(path):
            raise ValueError("Built-in presets are read-only and cannot be deleted.")
        if path.exists():
            path.unlink()

    def exists_custom_name(self, name: str) -> bool:
        target = (_slugify(name) + ".json").lower()
        for item in self.list_custom():
            if item.path.name.lower() == target or item.name.lower() == name.lower():
                return True
        return False

    def _scan(self, is_builtin: bool) -> list[PresetFileInfo]:
        if not self.root_dir.exists():
            return []
        items: list[PresetFileInfo] = []
        for fp in sorted(self.root_dir.rglob("*.json")):
            if self._is_custom_path(fp) == is_builtin:
                continue
            try:
                model = PresetSerializer.load_file(fp)
            except Exception:
                continue
            rel_parent = fp.parent.relative_to(self.root_dir)
            display_group = str(rel_parent) if str(rel_parent) != "." else "root"
            items.append(
                PresetFileInfo(
                    name=model.name,
                    path=fp,
                    ruleset_id=model.ruleset_id,
                    is_builtin=is_builtin,
                    display_group=display_group,
                )
            )
        return items

    def _resolve(self, path_or_name: str | Path) -> Path:
        path = Path(path_or_name)
        if path.exists():
            return path
        if not path.is_absolute():
            custom_guess = self.custom_dir / path
            if custom_guess.exists():
                return custom_guess
            if not str(path).lower().endswith(".json"):
                custom_guess = self.custom_dir / f"{path}.json"
                if custom_guess.exists():
                    return custom_guess
        raise FileNotFoundError(f"Preset file not found: {path_or_name}")

    def _is_custom_path(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.custom_dir.resolve())
            return True
        except Exception:
            return False


def _slugify(name: str) -> str:
    safe = []
    for ch in name.strip():
        if ch.isalnum():
            safe.append(ch.lower())
        elif ch in ("-", "_"):
            safe.append(ch)
        else:
            safe.append("_")
    slug = "".join(safe).strip("_")
    return slug or "preset"
