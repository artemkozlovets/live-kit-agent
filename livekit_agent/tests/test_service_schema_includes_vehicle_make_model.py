from __future__ import annotations

from livekit_agent.tools import load_tool_schemas


def test_service_tools_schema_includes_vehicle_make_model() -> None:
    schemas = load_tool_schemas()

    add_service = next(schema for schema in schemas if schema["name"] == "add_service")
    add_params = add_service.get("parameters")
    assert isinstance(add_params, dict)
    add_props = add_params.get("properties")
    assert isinstance(add_props, dict)
    assert add_props.get("vehicle_make", {}).get("type") == "string"
    assert add_props.get("vehicle_model", {}).get("type") == "string"

    update_service_order = next(schema for schema in schemas if schema["name"] == "update_service_order")
    update_params = update_service_order.get("parameters")
    assert isinstance(update_params, dict)
    update_props = update_params.get("properties")
    assert isinstance(update_props, dict)
    updates = update_props.get("updates")
    assert isinstance(updates, dict)
    updates_props = updates.get("properties")
    assert isinstance(updates_props, dict)
    assert updates_props.get("vehicle_make", {}).get("type") == "string"
    assert updates_props.get("vehicle_model", {}).get("type") == "string"

