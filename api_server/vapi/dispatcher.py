"""Vapi tool-call dispatcher.

This module maps Vapi tool names to handler functions.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from api_server.server.dependencies import DatabaseClient
from api_server.vapi.handlers.case_status import handle_get_case_status
from api_server.vapi.handlers.order import handle_store_service_order, handle_update_service_order
from api_server.vapi.handlers.phone import (
    handle_check_customer,
    handle_register_new_customer,
    handle_send_confirmation_sms,
    handle_update_customer,
    handle_validate_phone,
)
from api_server.vapi.handlers.session import (
    handle_add_service,
    handle_confirm_services,
    handle_get_session_summary,
)
from api_server.vapi.handlers.vehicle import handle_check_vin_database, handle_validate_vin
from api_server.vapi.session_store import SessionStore
from api_server.vapi.tool_call_parsing import get_tool_name


ToolHandler = Callable[
    [dict[str, Any], dict[str, Any], SessionStore, DatabaseClient],
    dict[str, Any] | Awaitable[dict[str, Any]],
]


TOOL_REGISTRY: dict[str, ToolHandler] = {
    "validate_phone": handle_validate_phone,
    "check_customer": handle_check_customer,
    "register_new_customer": handle_register_new_customer,
    "validate_vin": handle_validate_vin,
    "check_vin_database": handle_check_vin_database,
    "add_service": handle_add_service,
    "confirm_services": handle_confirm_services,
    "get_session_summary": handle_get_session_summary,
    "get_case_status": handle_get_case_status,
    "store_service_order": handle_store_service_order,
    "update_customer": handle_update_customer,
    "update_service_order": handle_update_service_order,
    "send_confirmation_sms": handle_send_confirmation_sms,
}


async def dispatch_tool_call(
    *,
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    """Dispatch a tool call to the registered handler.

    Args:
        tool_call: Single tool call entry from `message.toolCallList`
        message_payload: Full Vapi `message` object (not just nested values)
        session_store: Per-call in-memory store
        database_client: Backend database client (dependency-injected)
    """
    tool_name = get_tool_name(tool_call)
    tool_handler = TOOL_REGISTRY.get(tool_name)
    if tool_handler is None:
        return {"error": f"Unknown tool: {tool_name}"}

    result = tool_handler(tool_call, message_payload, session_store, database_client)
    return await result if inspect.isawaitable(result) else result
