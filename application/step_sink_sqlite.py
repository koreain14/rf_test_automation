# application/step_sink_sqlite.py
from __future__ import annotations
from typing import Any, Dict

from domain.steps import StepResult
from infrastructure.run_repo_sqlite import RunRepositorySQLite


class StepResultSinkSQLite:
    def __init__(self, run_repo: RunRepositorySQLite, project_id: str):
        self.run_repo = run_repo
        self.project_id = project_id

    def write(self, result_id: str, r: StepResult) -> None:
        self.run_repo.append_step_result(
            project_id=self.project_id,
            result_id=result_id,
            step_name=r.step_name,
            status=r.status,
            artifact_uri=r.artifact_uri,
            data=r.data,
        )