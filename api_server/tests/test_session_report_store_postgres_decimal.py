import json
import os
from decimal import Decimal
from typing import Any

import pytest


class _FakeConnection:
    def __init__(self) -> None:
        self._fetchone: tuple[Any, ...] | None = None
        self._fetchall: list[tuple[Any, ...]] = []

    def cursor(self) -> "_FakeConnection":
        return self

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        # These tests only care about how returned values are handled.
        _ = (sql, params)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._fetchone

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._fetchall)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def _install_fake_psycopg2(monkeypatch: pytest.MonkeyPatch, conn: _FakeConnection) -> None:
    import psycopg2

    def _connect(_: str) -> _FakeConnection:
        return conn

    monkeypatch.setattr(psycopg2, "connect", _connect)


def test_session_report_store_converts_decimal_epoch_from_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    # psycopg2 returns NUMERIC columns as Decimal by default.
    monkeypatch.delenv("USE_IN_MEMORY_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://example.invalid/db")

    conn = _FakeConnection()
    conn._fetchone = (json.dumps({"a": 1}), Decimal("123.0"))
    _install_fake_psycopg2(monkeypatch, conn)

    from api_server.observability.session_report_store import SessionReportStore

    store = SessionReportStore()
    assert store.get("room-123") == {"report": {"a": 1}, "received_at_unix_s": 123.0}


def test_session_report_store_list_converts_decimal_epochs_from_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USE_IN_MEMORY_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://example.invalid/db")

    conn = _FakeConnection()
    conn._fetchall = [("room-2", Decimal("2.0")), ("room-1", Decimal("1.0"))]
    _install_fake_psycopg2(monkeypatch, conn)

    from api_server.observability.session_report_store import SessionReportStore

    store = SessionReportStore()
    assert store.list(limit=10) == [
        {"room_name": "room-2", "received_at_unix_s": 2.0},
        {"room_name": "room-1", "received_at_unix_s": 1.0},
    ]


def test_session_report_store_returns_none_when_epoch_is_not_numeric(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USE_IN_MEMORY_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://example.invalid/db")

    conn = _FakeConnection()
    conn._fetchone = (json.dumps({"a": 1}), "not-a-number")
    _install_fake_psycopg2(monkeypatch, conn)

    from api_server.observability.session_report_store import SessionReportStore

    store = SessionReportStore()
    assert store.get("room-123") == {"report": {"a": 1}, "received_at_unix_s": None}

