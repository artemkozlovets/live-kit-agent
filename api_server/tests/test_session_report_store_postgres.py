import json
import os
from typing import Any

import pytest


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._fetchone: tuple[Any, ...] | None = None
        self._fetchall: list[tuple[Any, ...]] = []
        self.committed = False
        self.closed = False

    def cursor(self) -> "_FakeConnection":
        return self

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._fetchone

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._fetchall)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def _install_fake_psycopg2(monkeypatch: pytest.MonkeyPatch, conn: _FakeConnection) -> None:
    import psycopg2

    def _connect(_: str) -> _FakeConnection:
        return conn

    monkeypatch.setattr(psycopg2, "connect", _connect)


def test_session_report_store_uses_postgres_when_database_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USE_IN_MEMORY_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://example.invalid/db")

    conn = _FakeConnection()
    _install_fake_psycopg2(monkeypatch, conn)

    from api_server.observability.session_report_store import SessionReportStore

    store = SessionReportStore()
    store.set("room-123", {"report": {"hello": "world"}, "received_at_unix_s": 123.0})

    assert conn.committed is True
    assert conn.closed is True
    assert any("INSERT INTO session_reports" in sql for (sql, _) in conn.executed)


def test_session_report_store_reads_report_from_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USE_IN_MEMORY_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://example.invalid/db")

    conn = _FakeConnection()
    conn._fetchone = (json.dumps({"a": 1}), 123.0)
    _install_fake_psycopg2(monkeypatch, conn)

    from api_server.observability.session_report_store import SessionReportStore

    store = SessionReportStore()
    result = store.get("room-123")

    assert result == {"report": {"a": 1}, "received_at_unix_s": 123.0}


def test_session_report_store_lists_reports_from_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USE_IN_MEMORY_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://example.invalid/db")

    conn = _FakeConnection()
    conn._fetchall = [("room-2", 2.0), ("room-1", 1.0)]
    _install_fake_psycopg2(monkeypatch, conn)

    from api_server.observability.session_report_store import SessionReportStore

    store = SessionReportStore()
    result = store.list(limit=10)

    assert result == [
        {"room_name": "room-2", "received_at_unix_s": 2.0},
        {"room_name": "room-1", "received_at_unix_s": 1.0},
    ]


def test_session_report_store_falls_back_to_memory_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from api_server.observability.session_report_store import SessionReportStore

    store = SessionReportStore()
    store.set("room-123", {"report": {"hello": "world"}, "received_at_unix_s": 1.0})

    assert store.get("room-123") == {"report": {"hello": "world"}, "received_at_unix_s": 1.0}

