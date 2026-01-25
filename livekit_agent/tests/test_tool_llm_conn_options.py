import os
from typing import Any

import pytest

os.environ.setdefault("NUM_CPUS", "2")

try:
    import livekit.agents  # noqa: F401
except Exception as exc:  # pragma: no cover
    pytest.skip(f"livekit.agents unavailable in this environment: {exc}", allow_module_level=True)

from livekit.agents.types import APIConnectOptions  # noqa: E402

from livekit_agent.agent import VapiAdapterAgent  # noqa: E402
from livekit_agent.backend_tools_client import BackendToolsClient  # noqa: E402


class _RecordingToolLLM:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    class _Stream:
        async def __aenter__(self) -> "_RecordingToolLLM._Stream":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        def __aiter__(self) -> "_RecordingToolLLM._Stream":
            return self

        async def __anext__(self) -> Any:
            raise StopAsyncIteration

    def chat(self, **kwargs: Any) -> "_RecordingToolLLM._Stream":
        self.kwargs = dict(kwargs)
        return self._Stream()


@pytest.mark.asyncio
async def test_tool_llm_conn_options_can_be_overridden_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_LLM_TIMEOUT_S", "12.5")
    monkeypatch.setenv("GOOGLE_LLM_MAX_RETRY", "7")
    monkeypatch.setenv("GOOGLE_LLM_RETRY_INTERVAL_S", "1.25")

    tool_llm = _RecordingToolLLM()

    async def post_json(_: str, __: dict[str, Any]) -> dict[str, Any]:
        return {"results": []}

    agent = VapiAdapterAgent(
        backend_client=BackendToolsClient(tools_url="https://example.test/vapi/tools", post_json=post_json),
        call_id_fallback="room-test",
        sip_phone_number=None,
        tool_llm=tool_llm,  # type: ignore[arg-type]
    )

    await agent._tool_calls_from_instruction("Collect vehicle info and service complaint.")

    assert tool_llm.kwargs is not None
    conn_options = tool_llm.kwargs.get("conn_options")
    assert isinstance(conn_options, APIConnectOptions)
    assert conn_options.timeout == 12.5
    assert conn_options.max_retry == 7
    assert conn_options.retry_interval == 1.25

