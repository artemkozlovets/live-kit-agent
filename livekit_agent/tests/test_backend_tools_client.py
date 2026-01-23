import json

import pytest

from livekit_agent.backend_tools_client import (
    BackendToolsClient,
    BackendToolsTransportError,
    ToolResultMissingError,
    ToolResultParseError,
)


@pytest.mark.asyncio
async def test_backend_tools_client_parses_tool_result() -> None:
    async def fake_post_json(url: str, payload: dict) -> dict:
        assert url == "https://backend.test/vapi/tools"
        assert payload["message"]["call"]["id"] == "room-1"
        return {
            "results": [
                {"toolCallId": "tool-call-1", "result": json.dumps({"ok": True})},
            ],
            "destination": {"type": "assistant", "assistantId": "ignored"},
        }

    client = BackendToolsClient(
        tools_url="https://backend.test/vapi/tools",
        post_json=fake_post_json,
    )

    result = await client.call_tool(
        call_id="room-1",
        sip_phone_number="+15551230000",
        confirmed_callback_number="+15551230000",
        tool_call_id="tool-call-1",
        tool_name="validate_phone",
        tool_arguments={"phone_number": "+15551230000"},
    )

    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_backend_tools_client_selects_matching_tool_call_id() -> None:
    async def fake_post_json(url: str, payload: dict) -> dict:
        _ = url
        _ = payload
        return {
            "results": [
                {"toolCallId": "tool-call-other", "result": json.dumps({"ok": False})},
                {"toolCallId": "tool-call-1", "result": json.dumps({"ok": True})},
            ],
            "destination": {"type": "assistant", "assistantId": "ignored"},
        }

    client = BackendToolsClient(tools_url="https://backend.test/vapi/tools", post_json=fake_post_json)

    result = await client.call_tool(
        call_id="room-1",
        sip_phone_number=None,
        confirmed_callback_number=None,
        tool_call_id="tool-call-1",
        tool_name="get_case_status",
        tool_arguments={"last_user_message": "Hi"},
    )

    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_backend_tools_client_missing_tool_call_id_raises() -> None:
    async def fake_post_json(url: str, payload: dict) -> dict:
        _ = url
        _ = payload
        return {"results": [{"toolCallId": "tool-call-other", "result": json.dumps({"ok": True})}]}

    client = BackendToolsClient(tools_url="https://backend.test/vapi/tools", post_json=fake_post_json)

    with pytest.raises(ToolResultMissingError):
        await client.call_tool(
            call_id="room-1",
            sip_phone_number=None,
            confirmed_callback_number=None,
            tool_call_id="tool-call-1",
            tool_name="get_case_status",
            tool_arguments={"last_user_message": "Hi"},
        )


@pytest.mark.asyncio
async def test_backend_tools_client_invalid_result_raises() -> None:
    async def fake_post_json(url: str, payload: dict) -> dict:
        _ = url
        _ = payload
        return {"results": [{"toolCallId": "tool-call-1", "result": "not-json"}]}

    client = BackendToolsClient(tools_url="https://backend.test/vapi/tools", post_json=fake_post_json)

    with pytest.raises(ToolResultParseError):
        await client.call_tool(
            call_id="room-1",
            sip_phone_number=None,
            confirmed_callback_number=None,
            tool_call_id="tool-call-1",
            tool_name="get_case_status",
            tool_arguments={"last_user_message": "Hi"},
        )


@pytest.mark.asyncio
async def test_backend_tools_client_timeout_raises_explicit_error() -> None:
    async def fake_post_json(url: str, payload: dict) -> dict:
        _ = url
        _ = payload
        raise TimeoutError("boom")

    client = BackendToolsClient(tools_url="https://backend.test/vapi/tools", post_json=fake_post_json)

    with pytest.raises(BackendToolsTransportError):
        await client.call_tool(
            call_id="room-1",
            sip_phone_number=None,
            confirmed_callback_number=None,
            tool_call_id="tool-call-1",
            tool_name="get_case_status",
            tool_arguments={"last_user_message": "Hi"},
        )

