from pathlib import Path

import pytest

from livekit_agent.tools import load_tool_schemas


def test_load_tool_schemas_includes_expected_backend_tools() -> None:
    schemas = load_tool_schemas()
    names = {schema["name"] for schema in schemas}

    assert "get_case_status" in names
    assert "validate_phone" in names
    assert "check_customer" in names
    assert "register_new_customer" in names
    assert "add_service" in names
    assert "store_service_order" in names


def test_load_tool_schemas_includes_local_handoff_tools() -> None:
    schemas = load_tool_schemas()
    names = {schema["name"] for schema in schemas}

    assert "handoff_to_ServiceCollection" in names
    assert "handoff_to_Booking" in names
    assert "handoff_to_CustomerIntake" in names
    assert "transfer_to_human" in names


def test_load_tool_schemas_invalid_json_fails_fast(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON"):
        load_tool_schemas(assistant_paths=[bad])
