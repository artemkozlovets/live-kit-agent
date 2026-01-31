from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_DEFAULT_ASSISTANT_JSON_PATHS = [
    Path("squad/assistants/customer_intake.json"),
    Path("squad/assistants/service_collection.json"),
    Path("squad/assistants/booking.json"),
]

_LOCAL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "handoff_to_CustomerIntake",
        "description": "Move the flow back to customer intake.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "handoff_to_ServiceCollection",
        "description": "Move the flow to service collection.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "handoff_to_Booking",
        "description": "Move the flow to booking.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "transfer_to_human",
        "description": "Cold transfer the active phone caller to a human agent.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]


def load_tool_schemas(*, assistant_paths: list[Path] | None = None) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parent.parent
    paths = assistant_paths if assistant_paths is not None else _DEFAULT_ASSISTANT_JSON_PATHS

    schemas_by_name: dict[str, dict[str, Any]] = {}

    for schema in _LOCAL_TOOL_SCHEMAS:
        schemas_by_name[schema["name"]] = dict(schema)

    for rel_path in paths:
        path = rel_path if rel_path.is_absolute() else (root / rel_path)

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"Assistant JSON not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in assistant file: {path}") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"Assistant JSON must be an object: {path}")

        tools = payload.get("tools")
        if not isinstance(tools, list):
            continue

        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") != "function":
                continue

            function_payload = tool.get("function")
            if not isinstance(function_payload, dict):
                continue

            name = function_payload.get("name")
            if not isinstance(name, str) or not name.strip():
                continue

            schemas_by_name.setdefault(
                name,
                {
                    "name": name,
                    "description": function_payload.get("description", ""),
                    "parameters": function_payload.get("parameters", {}),
                },
            )

    return list(schemas_by_name.values())
