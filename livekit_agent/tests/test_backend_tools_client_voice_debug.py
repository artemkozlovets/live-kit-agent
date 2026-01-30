import logging

import pytest


@pytest.mark.asyncio
async def test_backend_tools_client_voice_debug_emits_info_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("VOICE_DEBUG", "1")
    monkeypatch.setenv("TOOLS_TOKEN", "test-token")

    from livekit_agent.backend_tools_client import BackendToolsClient

    async def _post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
        _ = url
        _ = payload
        _ = headers
        return {
            "results": [
                {
                    "tool_call_id": "tc-1",
                    "name": "validate_phone",
                    "ok": True,
                    "result": {"formatted": "+15551234567"},
                }
            ]
        }

    client = BackendToolsClient(tools_url="http://example.test/tools", post_json=_post_json)

    caplog.set_level(logging.INFO, logger="livekit-agent.backend-tools")
    await client.call_tool(
        call_id="+13053179840_room",
        sip_phone_number="+13053179840",
        confirmed_callback_number=None,
        tool_call_id="tc-1",
        tool_name="validate_phone",
        tool_arguments={"phone_number": "+1 (555) 123-4567"},
    )

    messages = [rec.getMessage() for rec in caplog.records]
    assert any("VOICE_DEBUG backend_tool_start" in msg for msg in messages)
    assert any("VOICE_DEBUG backend_tool_ok" in msg for msg in messages)

