"""Session report storage (in-memory by default, Postgres when configured).

Why this exists
---------------
LiveKit Cloud "Agent insights" is great, but it's UI-first. This repo exports a
session report (JSON) from the agent at the end of each session. The backend
needs a place to store that report so it can be fetched programmatically.

Storage strategy
----------------
- If `DATABASE_URL` is set (and `USE_IN_MEMORY_DB` is not), store reports in Postgres.
- Otherwise, store in-memory (useful for local dev and tests).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from decimal import Decimal
from typing import Any


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    return None


class SessionReportStore:
    def __init__(self) -> None:
        self._by_room_name: dict[str, dict[str, Any]] = {}

    def _local_reports_dir(self) -> pathlib.Path | None:
        base = os.getenv("LOCAL_OBSERVABILITY_DIR", "").strip()
        if not base:
            return None
        return pathlib.Path(base) / "session-reports"

    def _local_report_path(self, room_name: str) -> pathlib.Path | None:
        reports_dir = self._local_reports_dir()
        if reports_dir is None:
            return None

        # Reason: Room names can contain characters not safe for filenames.
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", room_name.strip()) or "room"
        return reports_dir / f"{safe}.json"

    def _write_local(self, room_name: str, entry: dict[str, Any]) -> None:
        path = self._local_report_path(room_name)
        if path is None:
            return

        reports_dir = path.parent
        reports_dir.mkdir(parents=True, exist_ok=True)

        report_obj = entry.get("report")
        report_dict = report_obj if isinstance(report_obj, dict) else {}

        received_at = entry.get("received_at_unix_s")
        received_at_unix_s = _to_float(received_at)
        if received_at_unix_s is None:
            received_at_unix_s = 0.0

        payload = {
            "room_name": room_name,
            "report": report_dict,
            "received_at_unix_s": received_at_unix_s,
        }

        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=True, default=str), encoding="utf-8")
        os.replace(tmp_path, path)

    def _read_local(self, room_name: str) -> dict[str, Any] | None:
        path = self._local_report_path(room_name)
        if path is None or not path.exists():
            return None

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, dict):
            return None

        report_obj = parsed.get("report")
        report_dict = report_obj if isinstance(report_obj, dict) else {}

        received_at = parsed.get("received_at_unix_s")
        received_at_unix_s = _to_float(received_at)
        if received_at_unix_s is None:
            received_at_unix_s = 0.0

        return {"report": report_dict, "received_at_unix_s": received_at_unix_s}

    def _database_url(self) -> str | None:
        # Reason: allow explicit override for local debug/tests.
        if _truthy_env("USE_IN_MEMORY_DB"):
            return None
        url = os.getenv("DATABASE_URL", "").strip()
        return url or None

    def get(self, room_name: str) -> dict[str, Any] | None:
        database_url = self._database_url()
        if database_url:
            return self._get_from_postgres(database_url, room_name)

        report = self._by_room_name.get(room_name)
        if isinstance(report, dict):
            return dict(report)

        # Reason: Local dev often runs without Postgres; persist to disk so reports
        # survive process restarts.
        return self._read_local(room_name)

    def set(self, room_name: str, report: dict[str, Any]) -> None:
        database_url = self._database_url()
        if database_url:
            self._upsert_to_postgres(database_url, room_name, report)
            return

        entry = dict(report)
        self._by_room_name[room_name] = entry
        self._write_local(room_name, entry)

    def clear(self, room_name: str) -> None:
        self._by_room_name.pop(room_name, None)
        path = self._local_report_path(room_name)
        if path is not None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def list(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Return stored reports (metadata only) sorted by received time desc."""

        database_url = self._database_url()
        if database_url:
            return self._list_from_postgres(database_url, limit=limit)

        items_by_room: dict[str, dict[str, Any]] = {}
        for room_name, entry in self._by_room_name.items():
            received_at = entry.get("received_at_unix_s") if isinstance(entry, dict) else None
            items_by_room[room_name] = {"room_name": room_name, "received_at_unix_s": received_at}

        reports_dir = self._local_reports_dir()
        if reports_dir is not None and reports_dir.exists():
            for path in reports_dir.glob("*.json"):
                try:
                    raw = path.read_text(encoding="utf-8")
                    parsed = json.loads(raw)
                except Exception:
                    continue

                if not isinstance(parsed, dict):
                    continue

                room_name_value = parsed.get("room_name")
                if not isinstance(room_name_value, str) or not room_name_value.strip():
                    continue

                received_at = parsed.get("received_at_unix_s")
                received_at_unix_s = _to_float(received_at)
                item = {"room_name": room_name_value, "received_at_unix_s": received_at_unix_s}

                existing = items_by_room.get(room_name_value)
                if existing is None:
                    items_by_room[room_name_value] = item
                    continue

                existing_ts = _to_float(existing.get("received_at_unix_s"))
                if (received_at_unix_s or 0.0) > (existing_ts or 0.0):
                    items_by_room[room_name_value] = item

        items = list(items_by_room.values())

        def _sort_key(item: dict[str, Any]) -> float:
            value = item.get("received_at_unix_s")
            return float(value) if isinstance(value, (int, float)) else 0.0

        items.sort(key=_sort_key, reverse=True)
        if limit is not None:
            items = items[: max(limit, 0)]
        return items

    def _upsert_to_postgres(self, database_url: str, room_name: str, entry: dict[str, Any]) -> None:
        # Reason: only import psycopg2 when we actually need it.
        import psycopg2

        report_obj = entry.get("report")
        report_dict: dict[str, Any]
        if isinstance(report_obj, dict):
            report_dict = report_obj
        else:
            report_dict = {}

        received_at = entry.get("received_at_unix_s")
        received_at_unix_s = _to_float(received_at)
        if received_at_unix_s is None:
            received_at_unix_s = 0.0

        conn = psycopg2.connect(database_url)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO session_reports (room_name, report, received_at)
                VALUES (%s, %s::jsonb, to_timestamp(%s))
                ON CONFLICT (room_name)
                DO UPDATE SET report = EXCLUDED.report, received_at = EXCLUDED.received_at
                """,
                (room_name, json.dumps(report_dict), received_at_unix_s),
            )
            conn.commit()
        finally:
            conn.close()

    def _get_from_postgres(self, database_url: str, room_name: str) -> dict[str, Any] | None:
        import psycopg2

        conn = psycopg2.connect(database_url)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT report::text, EXTRACT(EPOCH FROM received_at)
                FROM session_reports
                WHERE room_name = %s
                """,
                (room_name,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if row is None:
            return None

        raw_report, received_at = row[0], row[1]
        report: dict[str, Any] = {}
        if isinstance(raw_report, str) and raw_report.strip():
            try:
                parsed = json.loads(raw_report)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                report = parsed

        received_at_unix_s = _to_float(received_at)
        return {"report": report, "received_at_unix_s": received_at_unix_s}

    def _list_from_postgres(self, database_url: str, *, limit: int | None) -> list[dict[str, Any]]:
        import psycopg2

        effective_limit = 20 if limit is None else max(int(limit), 0)

        conn = psycopg2.connect(database_url)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT room_name, EXTRACT(EPOCH FROM received_at)
                FROM session_reports
                ORDER BY received_at DESC
                LIMIT %s
                """,
                (effective_limit,),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        items: list[dict[str, Any]] = []
        for room_name_value, received_at in rows:
            room_name_str = str(room_name_value)
            received_at_unix_s = _to_float(received_at)
            items.append({"room_name": room_name_str, "received_at_unix_s": received_at_unix_s})
        return items
