"""SMS message storage (in-memory by default, Postgres when configured).

Why this exists
---------------
When we send confirmation SMS, we want to store the Twilio MessageSid so we can:
- correlate delivery callbacks (`MessageStatus`, `ErrorCode`, etc.)
- debug failures after the call has ended

Storage strategy
----------------
- If `DATABASE_URL` is set (and `USE_IN_MEMORY_DB` is not), store rows in Postgres.
- Otherwise, store in-memory (useful for local dev and tests).
"""

from __future__ import annotations

import os
import re
import time
from typing import Any


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _last4(value: str | None) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits[-4:] if len(digits) >= 4 else None


class SmsMessageStore:
    def __init__(self) -> None:
        self._by_message_sid: dict[str, dict[str, Any]] = {}

    def _database_url(self) -> str | None:
        if _truthy_env("USE_IN_MEMORY_DB"):
            return None
        url = os.getenv("DATABASE_URL", "").strip()
        return url or None

    def record_outbound_message(
        self,
        *,
        message_sid: str,
        call_id: str | None,
        to_number: str | None,
        from_number: str | None,
        status: str | None,
    ) -> None:
        entry = {
            "message_sid": message_sid,
            "call_id": call_id,
            "to_last4": _last4(to_number),
            "from_last4": _last4(from_number),
            "status": status,
            "error_code": None,
            "error_message": None,
            "created_at_unix_s": time.time(),
            "updated_at_unix_s": time.time(),
        }

        database_url = self._database_url()
        if database_url:
            self._upsert_to_postgres(database_url, entry)
            return

        self._by_message_sid[message_sid] = entry

    def update_status(
        self,
        *,
        message_sid: str,
        status: str | None,
        error_code: int | None,
        error_message: str | None,
        to_number: str | None = None,
        from_number: str | None = None,
    ) -> None:
        existing = self._by_message_sid.get(message_sid)
        entry: dict[str, Any]
        if isinstance(existing, dict):
            entry = dict(existing)
        else:
            entry = {
                "message_sid": message_sid,
                "call_id": None,
                "to_last4": _last4(to_number),
                "from_last4": _last4(from_number),
                "created_at_unix_s": time.time(),
            }

        if to_number is not None:
            entry["to_last4"] = _last4(to_number)
        if from_number is not None:
            entry["from_last4"] = _last4(from_number)

        entry["status"] = status
        entry["error_code"] = error_code
        entry["error_message"] = error_message
        entry["updated_at_unix_s"] = time.time()

        database_url = self._database_url()
        if database_url:
            self._update_status_in_postgres(database_url, entry)
            return

        self._by_message_sid[message_sid] = entry

    def get(self, message_sid: str) -> dict[str, Any] | None:
        database_url = self._database_url()
        if database_url:
            return self._get_from_postgres(database_url, message_sid)

        entry = self._by_message_sid.get(message_sid)
        return dict(entry) if isinstance(entry, dict) else None

    def _upsert_to_postgres(self, database_url: str, entry: dict[str, Any]) -> None:
        import psycopg2

        conn = psycopg2.connect(database_url)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO sms_messages (
                  message_sid,
                  call_id,
                  to_last4,
                  from_last4,
                  status,
                  error_code,
                  error_message
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_sid)
                DO UPDATE SET
                  call_id = EXCLUDED.call_id,
                  to_last4 = EXCLUDED.to_last4,
                  from_last4 = EXCLUDED.from_last4,
                  status = EXCLUDED.status,
                  error_code = EXCLUDED.error_code,
                  error_message = EXCLUDED.error_message,
                  updated_at = now()
                """,
                (
                    entry.get("message_sid"),
                    entry.get("call_id"),
                    entry.get("to_last4"),
                    entry.get("from_last4"),
                    entry.get("status"),
                    entry.get("error_code"),
                    entry.get("error_message"),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _update_status_in_postgres(self, database_url: str, entry: dict[str, Any]) -> None:
        import psycopg2

        conn = psycopg2.connect(database_url)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO sms_messages (
                  message_sid,
                  to_last4,
                  from_last4,
                  status,
                  error_code,
                  error_message
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_sid)
                DO UPDATE SET
                  to_last4 = COALESCE(EXCLUDED.to_last4, sms_messages.to_last4),
                  from_last4 = COALESCE(EXCLUDED.from_last4, sms_messages.from_last4),
                  status = EXCLUDED.status,
                  error_code = EXCLUDED.error_code,
                  error_message = EXCLUDED.error_message,
                  updated_at = now()
                """,
                (
                    entry.get("message_sid"),
                    entry.get("to_last4"),
                    entry.get("from_last4"),
                    entry.get("status"),
                    entry.get("error_code"),
                    entry.get("error_message"),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _get_from_postgres(self, database_url: str, message_sid: str) -> dict[str, Any] | None:
        import psycopg2

        conn = psycopg2.connect(database_url)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                  message_sid,
                  call_id,
                  to_last4,
                  from_last4,
                  status,
                  error_code,
                  error_message,
                  EXTRACT(EPOCH FROM created_at),
                  EXTRACT(EPOCH FROM updated_at)
                FROM sms_messages
                WHERE message_sid = %s
                """,
                (message_sid,),
            )
            row = cur.fetchone()
            if row is None:
                return None

            (
                sid,
                call_id,
                to_last4,
                from_last4,
                status,
                error_code,
                error_message,
                created_at_unix_s,
                updated_at_unix_s,
            ) = row

            return {
                "message_sid": sid,
                "call_id": call_id,
                "to_last4": to_last4,
                "from_last4": from_last4,
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "created_at_unix_s": float(created_at_unix_s) if created_at_unix_s else None,
                "updated_at_unix_s": float(updated_at_unix_s) if updated_at_unix_s else None,
            }
        finally:
            conn.close()


# Reason: shared singleton store for both send + webhook handlers.
sms_message_store = SmsMessageStore()

