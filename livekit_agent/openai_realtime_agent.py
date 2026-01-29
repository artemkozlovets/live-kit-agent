from __future__ import annotations

import json
import re
import uuid
from typing import Any

from livekit.agents import Agent, ChatContext, function_tool

from livekit_agent.backend_tools_client import BackendToolsClientError
from livekit_agent.tools import load_tool_schemas


_PHONE_AFTER_LABEL_RE = re.compile(
    r"\b(?:phone(?:\s+number)?|callback(?:\s+number)?)\s*(?:is|:)\s*([+0-9][0-9\s\-\(\)]{8,}[0-9])",
    flags=re.IGNORECASE,
)
_PHONE_ANYWHERE_RE = re.compile(r"(\+?\d[\d\s\-\(\)]{8,}\d)")


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _extract_phone_candidate(text: str) -> str | None:
    match = _PHONE_AFTER_LABEL_RE.search(text)
    if match:
        candidate = match.group(1).strip().rstrip(".,;:!?")
        if len(_digits_only(candidate)) >= 10:
            return candidate

    for match in _PHONE_ANYWHERE_RE.finditer(text):
        candidate = match.group(1).strip().rstrip(".,;:!?")
        digits = _digits_only(candidate)
        if 10 <= len(digits) <= 15:
            return candidate

    return None


class OpenAIRealtimeAgent(Agent):
    """OpenAI Realtime cutover agent (text-mode friendly).

    Big picture:
    - Optional backend-first mode:
      - Call `get_case_status` on every user turn (backend-first guardrails).
      - Inject the case status into the turn context.
    - Optional OpenAI-first mode:
      - Let the realtime model manage the conversation state directly.
      - Use backend tools only for validation/persistence (minimal backend "policy").
    - Delegate reply generation to the session LLM (`session.generate_reply`).
    """

    def __init__(
        self,
        *,
        backend_client: Any,
        use_backend_guardrails: bool = True,
        call_id_fallback: str = "local-session",
        sip_phone_number: str | None = None,
        confirmed_callback_number: str | None = None,
        assistant_variable_values: dict[str, str] | None = None,
    ) -> None:
        tools = []
        for schema in load_tool_schemas():
            name = schema.get("name") if isinstance(schema, dict) else None
            if not isinstance(name, str) or not name.strip():
                continue
            if name == "get_case_status":
                continue
            if name.startswith("handoff_to_"):
                continue

            description = schema.get("description") if isinstance(schema, dict) else None
            parameters = schema.get("parameters") if isinstance(schema, dict) else None
            raw_schema = {
                "name": name,
                "description": description if isinstance(description, str) else "",
                "parameters": parameters if isinstance(parameters, dict) else {},
            }

            async def _tool(raw_arguments: dict[str, object], context: Any, *, _name: str = name) -> dict[str, Any]:
                _ = context
                return await self.forward_tool(tool_name=_name, tool_arguments=dict(raw_arguments))

            tools.append(function_tool(_tool, raw_schema=raw_schema))

        super().__init__(
            instructions=(
                "You are Grace, a helpful voice agent for American Fleet Services (AFS).\n"
                "\n"
                "Conversation style:\n"
                "- The caller may give a large info-dump (name, phone, address, etc.) in any order.\n"
                "- Extract everything you can from each turn.\n"
                "- Do NOT ask rigid one-by-one questions. If multiple things are missing, ask for them together.\n"
                "- If the caller says 'start over' / 'throw away that info', discard the previously collected details and continue fresh.\n"
                "\n"
                "Tools:\n"
                "- Use tools to validate and save customer data (validate_phone, check_customer, register_new_customer, update_customer, etc.).\n"
                "- When you have a phone number, call validate_phone and then check_customer. Do not claim you are \"checking\" unless you actually called the tool.\n"
                "- Prefer saving in as few tool calls as possible once you have enough information.\n"
                "\n"
                "Guardrails:\n"
                "- If you receive a system message containing JSON like {\"case_status\": ...}, treat it as authoritative backend guidance.\n"
                "- If you receive a system message containing JSON like {\"tool_prefetch\": ...}, treat it as authoritative tool results.\n"
            ),
            tools=tools,
        )
        self._backend = backend_client
        self._use_backend_guardrails = use_backend_guardrails
        self._call_id_fallback = call_id_fallback
        self._sip_phone_number = sip_phone_number
        self._confirmed_callback_number = confirmed_callback_number
        self._assistant_variable_values = assistant_variable_values
        self._validated_phone_number = confirmed_callback_number
        self._customer_checked = False
        self._fatal_error = False

    @property
    def call_id(self) -> str:
        room = getattr(self.session, "room", None)
        room_name = getattr(room, "name", None)
        if isinstance(room_name, str) and room_name.strip():
            return room_name
        return self._call_id_fallback

    async def _call_backend_tool(self, *, tool_name: str, tool_arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._backend.call_tool(
            call_id=self.call_id,
            sip_phone_number=self._sip_phone_number,
            confirmed_callback_number=self._confirmed_callback_number,
            assistant_variable_values=self._assistant_variable_values,
            tool_call_id=f"tool-{uuid.uuid4().hex}",
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: Any) -> None:
        if self._fatal_error:
            return

        user_text = getattr(new_message, "text_content", None) or ""
        user_text = user_text.strip()
        if not user_text:
            return

        if not self._use_backend_guardrails:
            tool_prefetch: dict[str, Any] = {}
            ready_for_customer_lookup = False

            phone_candidate = _extract_phone_candidate(user_text)
            if phone_candidate:
                normalized_candidate_digits = _digits_only(phone_candidate)
                normalized_validated_digits = (
                    _digits_only(self._validated_phone_number) if isinstance(self._validated_phone_number, str) else ""
                )
                if normalized_candidate_digits and normalized_candidate_digits != normalized_validated_digits:
                    self._customer_checked = False
                    try:
                        phone_validation = await self._call_backend_tool(
                            tool_name="validate_phone",
                            tool_arguments={"phone_number": phone_candidate},
                        )
                    except BackendToolsClientError:
                        self._speak_backend_unreachable_once()
                        return

                    tool_prefetch["validate_phone"] = phone_validation

                    formatted = phone_validation.get("formatted") if isinstance(phone_validation, dict) else None
                    if isinstance(formatted, str) and formatted.strip():
                        self._confirmed_callback_number = formatted.strip()
                        self._validated_phone_number = formatted.strip()
                        ready_for_customer_lookup = True
                    else:
                        proceed_unvalidated = (
                            phone_validation.get("proceed_unvalidated") if isinstance(phone_validation, dict) else None
                        )
                        if proceed_unvalidated is True:
                            # Reason: After max attempts, proceed anyway to avoid frustrating the caller.
                            self._validated_phone_number = phone_candidate
                            ready_for_customer_lookup = True
                        else:
                            ready_for_customer_lookup = False
                else:
                    ready_for_customer_lookup = True
            elif isinstance(self._validated_phone_number, str) and self._validated_phone_number:
                ready_for_customer_lookup = True

            if (
                not self._customer_checked
                and ready_for_customer_lookup
                and isinstance(self._validated_phone_number, str)
                and self._validated_phone_number
            ):
                try:
                    customer_lookup = await self._call_backend_tool(
                        tool_name="check_customer",
                        tool_arguments={"phone_number": self._validated_phone_number},
                    )
                except BackendToolsClientError:
                    self._speak_backend_unreachable_once()
                    return

                tool_prefetch["check_customer"] = customer_lookup
                self._customer_checked = True

            if tool_prefetch:
                turn_ctx.add_message(
                    role="system",
                    # Reason: Keep the injected context structured so the model can reliably parse it.
                    content=json.dumps({"tool_prefetch": tool_prefetch}, ensure_ascii=True, default=str),
                )

            self.session.generate_reply(user_input=user_text, chat_ctx=turn_ctx)
            return

        try:
            case_status = await self._call_backend_tool(
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
