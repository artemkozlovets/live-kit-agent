from livekit_agent.tools import load_tool_schemas


def test_add_service_schema_requires_vehicle_identifier() -> None:
    schemas = load_tool_schemas()
    add_service = next(schema for schema in schemas if schema["name"] == "add_service")

    params = add_service.get("parameters")
    assert isinstance(params, dict)
    assert params.get("type") == "object"

    required = params.get("required")
    assert isinstance(required, list)
    assert set(required) >= {
        "vehicle_identifier_type",
        "vehicle_identifier",
        "service_complaint",
        "service_location",
    }

    assert params.get("anyOf") is None

    properties = params.get("properties")
    assert isinstance(properties, dict)

    identifier_type = properties.get("vehicle_identifier_type")
    assert isinstance(identifier_type, dict)
    assert identifier_type.get("type") == "string"
    assert set(identifier_type.get("enum") or []) >= {"vin", "unit_number", "unit_nickname"}

    identifier = properties.get("vehicle_identifier")
    assert isinstance(identifier, dict)
    assert identifier.get("type") == "string"
