import json
import os

from fastapi.testclient import TestClient


def test_tools_v2_writes_local_trace_when_enabled(tmp_path, monkeypatch) -> None:
    # Reason: Local console debugging is painful without durable artifacts. When
    # enabled, we save a lightweight JSONL trace of each /tools request.
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")
    old_dir = os.environ.get("LOCAL_OBSERVABILITY_DIR")
    os.environ["LOCAL_OBSERVABILITY_DIR"] = str(tmp_path)
    try:
        from api_server.server.fastapi_app import app

        client = TestClient(app)

        payload = {
            "call": {"id": "room-1", "customer": {"number": "+15551234567"}},
            "customer": {"number": "+15551234567"},
            "tool_calls": [
                {"id": "tool-1", "name": "validate_phone", "arguments": {"phone_number": "+15551234567"}}
            ],
        }

        resp = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
        assert resp.status_code == 200

        trace_path = tmp_path / "backend.tools.jsonl"
        assert trace_path.exists()

        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        event = json.loads(lines[-1])

        assert event.get("call_id") == "room-1"
        assert event.get("tool_calls") == [
            {
                "tool_call_id": "tool-1",
                "tool_name": "validate_phone",
                "argument_keys": ["phone_number"],
                "result_keys": ["formatted", "is_mobile", "next_action", "valid"],
            }
        ]
    finally:
        if old_dir is None:
            os.environ.pop("LOCAL_OBSERVABILITY_DIR", None)
        else:
            os.environ["LOCAL_OBSERVABILITY_DIR"] = old_dir
