from __future__ import annotations

import json
import uuid
from typing import Any

from livekit.agents import Agent, ChatContext

from livekit_agent.backend_tools_client import BackendToolsClientError


class OpenAIRealtimeAgent(Agent):
    """OpenAI Realtime cutover agent (text-mode friendly).

    Big picture:
    - Call `get_case_status` on every user turn (backend-first guardrails).
    - Inject the case status into the turn context.
    - Delegate reply generation to the session LLM (`session.generate_reply`).
    """

    def __init__(
        self,
        *,
        backend_client: Any,
        call_id_fallback: str = "local-session",
        sip_phone_number: str | None = None,
        confirmed_callback_number: str | None = None,
        assistant_variable_values: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            instructions=(
                "You are a helpful voice agent. Follow backend guardrails and use tools when needed."
            )
        )
        self._backend = backend_client
        self._call_id_fallback = call_id_fallback
        self._sip_phone_number = sip_phone_number
        self._confirmed_callback_number = confirmed_callback_number
        self._assistant_variable_values = assistant_variable_values
        self._fatal_error = False

    @property
    def call_id(self) -> str:
        room = getattr(self.session, "room", None)
        room_name = getattr(room, "name", None)
        if isinstance(room_name, str) and room_name.strip():
            return room_name
        return self._call_id_fallback

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: Any) -> None:
        if self._fatal_error:
            return

        user_text = getattr(new_message, "text_content", None) or ""
        user_text = user_text.strip()
        if not user_text:
            return

        try:
            case_status = await self._backend.call_tool(
                call_id=self.call_id,
                sip_phone_number=self._sip_phone_number,
                confirmed_callback_number=self._confirmed_callback_number,
                assistant_variable_values=self._assistant_variable_values,
                tool_call_id=f"tool-{uuid.uuid4().hex}",
                tool_name="get_case_status",
                tool_arguments={"last_user_message": user_text, "expected_field": None},
            )
        except BackendToolsClientError:
            self._speak_backend_unreachable_once()
            return

        turn_ctx.add_message(
            role="system",
            # Reason: Keep the injected context structured so the model can reliably parse it.
            content=json.dumps({"case_status": case_status}, ensure_ascii=True, default=str),
        )

        self.session.generate_reply(user_input=user_text, chat_ctx=turn_ctx)

    async def forward_tool(self, *, tool_name: str, tool_arguments: dict[str, Any]) -> dict[str, Any]:
        """Forward an LLM tool call to the backend `/tools` API (v2)."""
        return await self._backend.call_tool(
            call_id=self.call_id,
            sip_phone_number=self._sip_phone_number,
            confirmed_callback_number=self._confirmed_callback_number,
            assistant_variable_values=self._assistant_variable_values,
            tool_call_id=f"tool-{uuid.uuid4().hex}",
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )

    def _speak_backend_unreachable_once(self) -> None:
        if self._fatal_error:
            return

        self._fatal_error = True
        self.session.say("I'm having trouble connecting — please call back.")

