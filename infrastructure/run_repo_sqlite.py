# infrastructure/run_repo_sqlite.py

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from application.result_difference import enrich_difference_fields
from .db import get_connection


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


class RunRepositorySQLite:
    def _load_step_payloads_by_result(self, project_id: str, result_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not result_ids:
            return {}

        conn = get_connection()
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in result_ids)
        cur.execute(
            f"""
            SELECT result_id, artifact_uri, data_json
            FROM step_results
            WHERE project_id = ? AND result_id IN ({placeholders})
            ORDER BY created_at ASC, rowid ASC
            """,
            [project_id, *result_ids],
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        merged: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            result_id = str(row.get("result_id", "") or "")
            if not result_id:
                continue
            payload = merged.setdefault(result_id, {})
            try:
                data = json.loads(row.get("data_json") or "{}")
            except Exception:
                data = {}
            if isinstance(data, dict):
                payload.update(data)
            artifact_uri = str(row.get("artifact_uri", "") or "")
            if artifact_uri:
                payload.setdefault("artifact_uri", artifact_uri)
                if not payload.get("screenshot_abs_path"):
                    payload["screenshot_abs_path"] = artifact_uri
        return merged

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



    def _parse_note_metadata(self, note: str) -> Dict[str, Any]:
        if not note:
            return {}
        try:
            data = json.loads(note)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def update_run_metadata(self, run_id: str, metadata: Dict[str, Any]):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT note FROM runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        current = self._parse_note_metadata(row["note"] if row else "")
        current.update(metadata or {})
        cur.execute(
            "UPDATE runs SET note = ? WHERE run_id = ?",
            (json.dumps(current, ensure_ascii=False), run_id),
        )
        conn.commit()
        conn.close()

    def get_run_metadata(self, run_id: str) -> Dict[str, Any]:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT note FROM runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        conn.close()
        return self._parse_note_metadata(row["note"] if row else "")
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
            r.note,
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
        for row in rows:
            meta = self._parse_note_metadata(row.get("note", ""))
            row["equipment_profile_name"] = meta.get("equipment_profile_name")
            row["analyzer_device_name"] = meta.get("analyzer_device_name")
            row["equipment_summary"] = meta.get("equipment_summary")
            row["run_metadata"] = meta
        return rows

    def get_failed_cases(self, project_id: str, run_id: str) -> List[Dict[str, Any]]:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
        SELECT res.test_type, res.band, res.standard, res.channel, res.bw_mhz, runs.note AS run_note
        FROM results res
        LEFT JOIN runs ON runs.run_id = res.run_id
        WHERE res.project_id = ? AND res.run_id = ? AND res.status = 'FAIL'
        """, (project_id, run_id))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        for row in rows:
            meta = self._parse_note_metadata(row.get("run_note", ""))
            row["equipment_profile_name"] = meta.get("equipment_profile_name")
            row["analyzer_device_name"] = meta.get("analyzer_device_name")
            row["equipment_summary"] = meta.get("equipment_summary")
            row["run_metadata"] = meta
        return rows
    
    # infrastructure/run_repo_sqlite.py

    def list_results(self, project_id: str, run_id: str, status: str | None = None, limit: int = 5000):
        """
        Results ???쒖떆??寃곌낵 由ъ뒪??
        ??result_id ?ы븿 (?좏깮??寃곌낵??step_results 議고쉶??
        ??measured_value / limit_value ?ы븿
        ??reason: step_results.data_json??理쒖떊 湲곕줉?먯꽌 異붿텧
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
                ORDER BY sr.created_at DESC, sr.rowid DESC
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
        merged_step_payloads = self._load_step_payloads_by_result(
            project_id=project_id,
            result_ids=[str(r.get('result_id', '') or '') for r in rows],
        )

        # tags_json?먯꽌 group 爰쇰궡湲?湲곗〈 ?좎?) :contentReference[oaicite:2]{index=2}
        for r in rows:
            last = dict(merged_step_payloads.get(str(r.get('result_id', '') or ''), {}) or {})
            tags = {}
            # group
            try:
                tags = json.loads(r.get("tags_json") or "{}")
                r["group"] = tags.get("group", "")
            except Exception:
                r["group"] = ""
                tags = {}

            # reason (last_step_data_json 湲곕컲)
            reason = ""
            try:
                latest = json.loads(r.get("last_step_data_json") or "{}")
                if isinstance(latest, dict):
                    last.update(latest)
                # ?뷀엳 ?곕뒗 ?ㅻ뱾???쒖꽌?濡??먯깋
                for k in ("reason", "message", "error", "exception", "detail", "desc"):
                    v = last.get(k)
                    if isinstance(v, str) and v.strip():
                        reason = v.strip()
                        break
                # nested ?뺥깭??理쒖냼 ???
                if not reason and isinstance(last.get("error"), dict):
                    v = last["error"].get("message") or last["error"].get("detail")
                    if isinstance(v, str):
                        reason = v.strip()
            except Exception:
                reason = ""

            r["reason"] = reason
            enriched = enrich_difference_fields(r, last)
            r["difference_value"] = enriched.get("difference_value")
            r["difference_unit"] = enriched.get("difference_unit", "")
            r["comparator"] = enriched.get("comparator", "")
            r["measurement_unit"] = str(
                last.get("display_measurement_unit")
                or last.get("measurement_unit")
                or r.get("difference_unit")
                or ""
            )
            r["measurement_profile_name"] = str(last.get("measurement_profile_name", "") or "")
            r["measurement_profile_source"] = str(last.get("measurement_profile_source", "") or "")
            r["measurement_method"] = str(
                last.get("scpi_measurement_method")
                or last.get("psd_method")
                or ""
            )
            r["screenshot_path"] = str(last.get("screenshot_path", "") or "")
            r["screenshot_abs_path"] = str(last.get("screenshot_abs_path", "") or "")
            r["has_screenshot"] = bool(r["screenshot_path"] or r["screenshot_abs_path"])
            r["voltage_condition"] = str(last.get("voltage_condition") or tags.get("voltage_condition") or "")
            r["nominal_voltage_v"] = (
                last.get("nominal_voltage_v")
                if last.get("nominal_voltage_v") not in (None, "")
                else tags.get("nominal_voltage_v")
            )
            r["target_voltage_v"] = (
                last.get("target_voltage_v")
                if last.get("target_voltage_v") not in (None, "")
                else tags.get("target_voltage_v")
            )
            r["last_step_data"] = last

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
        ORDER BY created_at ASC, rowid ASC
        """, (project_id, result_id))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        # data_json ?뚯떛 ?몄쓽
        for r in rows:
            try:
                r["data"] = json.loads(r.get("data_json") or "{}")
            except Exception:
                r["data"] = {}
        return rows


