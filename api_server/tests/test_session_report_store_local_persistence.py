import json
import os


def test_session_report_store_persists_to_disk_when_enabled(tmp_path) -> None:
    # Reason: In local dev we often run without Postgres, but still want durable
    # observability artifacts across restarts.
    old_dir = os.environ.get("LOCAL_OBSERVABILITY_DIR")
    os.environ["LOCAL_OBSERVABILITY_DIR"] = str(tmp_path)
    try:
        from api_server.observability.session_report_store import SessionReportStore

        store1 = SessionReportStore()
        store1.set("room-123", {"report": {"hello": "world"}, "received_at_unix_s": 123.0})

        # Simulate a new process by creating a new store instance.
        store2 = SessionReportStore()
        got = store2.get("room-123")
        assert got is not None
        assert got.get("report") == {"hello": "world"}
        assert got.get("received_at_unix_s") == 123.0

        listed = store2.list(limit=20)
        assert any(item.get("room_name") == "room-123" for item in listed)

        # Sanity check: the on-disk JSON is readable.
        reports_dir = tmp_path / "session-reports"
        files = list(reports_dir.glob("*.json"))
        assert files, "expected at least one persisted session report JSON file"
        parsed = json.loads(files[0].read_text(encoding="utf-8"))
        assert parsed.get("report") == {"hello": "world"}
    finally:
        if old_dir is None:
            os.environ.pop("LOCAL_OBSERVABILITY_DIR", None)
        else:
            os.environ["LOCAL_OBSERVABILITY_DIR"] = old_dir

