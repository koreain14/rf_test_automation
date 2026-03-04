from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from application.migrations_preset import migrate_preset_to_latest
from infrastructure.plan_repo_sqlite import PlanRepositorySQLite


def seed_presets_from_folder(
    repo: PlanRepositorySQLite,
    project_id: str,
    presets_dir: Path,
    update_policy: str = "if_ruleset_version_changed",
) -> Tuple[int, int]:
    """
    update_policy:
      - "never": DB에 있으면 절대 업데이트 안 함
      - "always": 파일이 있으면 항상 DB json_data를 덮어씀
      - "if_ruleset_version_changed": ruleset_version이 다를 때만 업데이트
      - "if_selection_changed": selection이 다르면 업데이트(권장X: 사용자가 DB에서 수정했으면 덮어쓸 위험)

    return: (inserted_count, updated_count)
    """
    inserted = 0
    updated = 0

    presets_dir = presets_dir.resolve()
    if not presets_dir.exists():
        return (0, 0)

    for fp in sorted(presets_dir.rglob("*.json")):
        with fp.open("r", encoding="utf-8") as f:
            raw: Dict[str, Any] = json.load(f)

        migrated, _ = migrate_preset_to_latest(raw)
        name = migrated["name"]

        existing_id = repo.find_preset_id_by_name(project_id, name)

        if existing_id is None:
            # insert
            repo.save_preset(
                project_id=project_id,
                name=migrated["name"],
                ruleset_id=migrated["ruleset_id"],
                ruleset_version=migrated["ruleset_version"],
                preset_json=migrated,
            )
            inserted += 1
            continue

        # update decision
        if update_policy == "never":
            continue

        if update_policy == "always":
            repo.update_preset_json(existing_id, migrated)
            updated += 1
            continue

        if update_policy == "if_ruleset_version_changed":
            cur = repo.load_preset(existing_id)
            cur_ver = cur.get("ruleset_version")
            if cur_ver != migrated.get("ruleset_version"):
                repo.update_preset_json(existing_id, migrated)
                updated += 1
            continue

        if update_policy == "if_selection_changed":
            cur = repo.load_preset(existing_id)
            cur_sel = cur.get("selection") if "selection" in cur else cur
            new_sel = migrated.get("selection")
            if cur_sel != new_sel:
                repo.update_preset_json(existing_id, migrated)
                updated += 1
            continue

        raise ValueError(f"Unknown update_policy: {update_policy}")

    return (inserted, updated)