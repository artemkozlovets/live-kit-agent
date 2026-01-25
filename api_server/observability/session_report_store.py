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
from typing import Any


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


class SessionReportStore:
    def __init__(self) -> None:
        self._by_room_name: dict[str, dict[str, Any]] = {}

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
        return dict(report) if isinstance(report, dict) else None

    def set(self, room_name: str, report: dict[str, Any]) -> None:
        database_url = self._database_url()
        if database_url:
            self._upsert_to_postgres(database_url, room_name, report)
            return

        self._by_room_name[room_name] = dict(report)

    def clear(self, room_name: str) -> None:
        self._by_room_name.pop(room_name, None)

    def list(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Return stored reports (metadata only) sorted by received time desc."""

        database_url = self._database_url()
        if database_url:
            return self._list_from_postgres(database_url, limit=limit)

        items: list[dict[str, Any]] = []
        for room_name, entry in self._by_room_name.items():
            received_at = None
            if isinstance(entry, dict):
                received_at = entry.get("received_at_unix_s")
            items.append({"room_name": room_name, "received_at_unix_s": received_at})

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
        received_at_unix_s = float(received_at) if isinstance(received_at, (int, float)) else None
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

        received_at_unix_s = float(received_at) if isinstance(received_at, (int, float)) else None
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
            received_at_unix_s = float(received_at) if isinstance(received_at, (int, float)) else None
            items.append({"room_name": room_name_str, "received_at_unix_s": received_at_unix_s})
        return items
