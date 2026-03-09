# infrastructure/run_repo_sqlite.py

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .db import get_connection


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class RunRepositorySQLite:
    def create_run(self, project_id: str, preset_id: str, parent_run_id: Optional[str] = None, note: str = "") -> str:
        run_id = str(uuid.uuid4())
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO runs (run_id, project_id, preset_id, started_at, finished_at, status, parent_run_id, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, project_id, preset_id, now(), None, "RUNNING", parent_run_id, note))
        conn.commit()
        conn.close()
        return run_id

    def finish_run(self, run_id: str, status: str):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
        UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?
        """, (now(), status, run_id))
        conn.commit()
        conn.close()

    def append_result(self, project_id: str, run_id: str, row: Dict[str, Any]) -> str:
        """
        row must include:
          test_key, tech, regulation, band, standard, test_type, channel, bw_mhz, status
        optional:
          margin_db, measured_value, limit_value, instrument_snapshot, tags
        """
        result_id = str(uuid.uuid4())
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
        INSERT INTO results (
          result_id, project_id, run_id,
          test_key, tech, regulation, band, standard, test_type, channel, bw_mhz,
          status, margin_db, measured_value, limit_value,
          instrument_snapshot_json, tags_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result_id, project_id, run_id,
            row["test_key"], row["tech"], row["regulation"], row["band"], row["standard"],
            row["test_type"], int(row["channel"]), int(row["bw_mhz"]),
            row["status"],
            row.get("margin_db"), row.get("measured_value"), row.get("limit_value"),
            json.dumps(row.get("instrument_snapshot", {}), ensure_ascii=False),
            json.dumps(row.get("tags", {}), ensure_ascii=False),
            now()
        ))

        conn.commit()
        conn.close()
        return result_id

    def list_recent_runs(self, project_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
        SELECT
            r.run_id,
            r.preset_id,
            r.started_at,
            r.status,
            p.name AS preset_name
        FROM runs r
        LEFT JOIN presets p
            ON r.project_id = p.project_id
        AND r.preset_id = p.preset_id
        WHERE r.project_id = ?
        ORDER BY r.started_at DESC
        LIMIT ?
        """, (project_id, int(limit)))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def get_failed_cases(self, project_id: str, run_id: str) -> List[Dict[str, Any]]:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
        SELECT test_type, band, standard, channel, bw_mhz
        FROM results
        WHERE project_id = ? AND run_id = ? AND status = 'FAIL'
        """, (project_id, run_id))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    
    # infrastructure/run_repo_sqlite.py

    def list_results(self, project_id: str, run_id: str, status: str | None = None, limit: int = 5000):
        """
        Results 탭 표시용 결과 리스트.
        ✅ result_id 포함 (선택한 결과의 step_results 조회용)
        ✅ measured_value / limit_value 포함
        ✅ reason: step_results.data_json의 최신 기록에서 추출
        """
        conn = get_connection()
        cur = conn.cursor()

        base_sql = """
        SELECT
            r.result_id,
            r.status,
            r.test_type,
            r.band,
            r.standard,
            r.channel,
            r.bw_mhz,
            r.margin_db,
            r.measured_value,
            r.limit_value,
            r.test_key,
            r.tags_json,
            (
                SELECT sr.data_json
                FROM step_results sr
                WHERE sr.project_id = r.project_id AND sr.result_id = r.result_id
                ORDER BY sr.created_at DESC
                LIMIT 1
            ) AS last_step_data_json
        FROM results r
        WHERE r.project_id = ? AND r.run_id = ?
        """

        params = [project_id, run_id]

        if status and status != "ALL":
            base_sql += " AND r.status = ?"
            params.append(status)

        base_sql += """
        ORDER BY r.created_at ASC
        LIMIT ?
        """
        params.append(int(limit))

        cur.execute(base_sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        # tags_json에서 group 꺼내기(기존 유지) :contentReference[oaicite:2]{index=2}
        for r in rows:
            # group
            try:
                tags = json.loads(r.get("tags_json") or "{}")
                r["group"] = tags.get("group", "")
            except Exception:
                r["group"] = ""

            # reason (last_step_data_json 기반)
            reason = ""
            try:
                last = json.loads(r.get("last_step_data_json") or "{}")
                # 흔히 쓰는 키들을 순서대로 탐색
                for k in ("reason", "message", "error", "exception", "detail", "desc"):
                    v = last.get(k)
                    if isinstance(v, str) and v.strip():
                        reason = v.strip()
                        break
                # nested 형태도 최소 대응
                if not reason and isinstance(last.get("error"), dict):
                    v = last["error"].get("message") or last["error"].get("detail")
                    if isinstance(v, str):
                        reason = v.strip()
            except Exception:
                reason = ""

            r["reason"] = reason

        return rows

    def get_run_status_counts(self, project_id: str, run_id: str) -> dict[str, int]:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM results
            WHERE project_id = ? AND run_id = ?
            GROUP BY status
            """,
            (project_id, run_id),
        )

        out = {"PASS": 0, "FAIL": 0, "SKIP": 0, "ERROR": 0}
        for row in cur.fetchall():
            status = row["status"]
            cnt = row["cnt"]
            if status in out:
                out[status] = cnt
            else:
                out[status] = cnt

        conn.close()
        return out


    def create_result_stub(self, project_id: str, run_id: str, row: Dict[str, Any]) -> str:
        """
        row must include:
          test_key, tech, regulation, band, standard, test_type, channel, bw_mhz
        """
        result_id = str(uuid.uuid4())
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
        INSERT INTO results (
          result_id, project_id, run_id,
          test_key, tech, regulation, band, standard, test_type, channel, bw_mhz,
          status, margin_db, measured_value, limit_value,
          instrument_snapshot_json, tags_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result_id, project_id, run_id,
            row["test_key"], row["tech"], row["regulation"], row["band"], row["standard"],
            row["test_type"], int(row["channel"]), int(row["bw_mhz"]),
            "RUNNING",
            None, None, None,
            json.dumps(row.get("instrument_snapshot", {}), ensure_ascii=False),
            json.dumps(row.get("tags", {}), ensure_ascii=False),
            now()
        ))

        conn.commit()
        conn.close()
        return result_id

    def update_result_final(
        self,
        result_id: str,
        status: str,
        margin_db: Optional[float] = None,
        measured_value: Optional[float] = None,
        limit_value: Optional[float] = None,
    ) -> None:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
        UPDATE results
        SET status=?, margin_db=?, measured_value=?, limit_value=?
        WHERE result_id=?
        """, (status, margin_db, measured_value, limit_value, result_id))
        conn.commit()
        conn.close()

    def append_step_result(
        self,
        project_id: str,
        result_id: str,
        step_name: str,
        status: str,
        data: Dict[str, Any],
        artifact_uri: Optional[str] = None,
    ) -> str:
        step_result_id = str(uuid.uuid4())
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO step_results (
          step_result_id, project_id, result_id,
          step_name, status, artifact_uri, data_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            step_result_id, project_id, result_id,
            step_name, status, artifact_uri,
            json.dumps(data or {}, ensure_ascii=False),
            now()
        ))
        conn.commit()
        conn.close()
        return step_result_id

    def list_step_results(self, project_id: str, result_id: str) -> List[Dict[str, Any]]:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
        SELECT step_name, status, artifact_uri, data_json, created_at
        FROM step_results
        WHERE project_id=? AND result_id=?
        ORDER BY created_at ASC
        """, (project_id, result_id))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        # data_json 파싱 편의
        for r in rows:
            try:
                r["data"] = json.loads(r.get("data_json") or "{}")
            except Exception:
                r["data"] = {}
        return rows
