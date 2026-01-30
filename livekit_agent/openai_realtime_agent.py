from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any

from livekit import rtc
from livekit.agents import Agent, ChatContext, function_tool

from livekit_agent.backend_tools_client import BackendToolsClientError
from livekit_agent.tools import load_tool_schemas

logger = logging.getLogger("livekit-agent.openai-realtime")


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

            async def _tool(
                raw_arguments: dict[str, object],
                context: Any | None = None,
                *,
                _name: str = name,
            ) -> dict[str, Any]:
                return await self.forward_tool(tool_name=_name, tool_arguments=dict(raw_arguments))

            tools.append(function_tool(_tool, raw_schema=raw_schema))

        super().__init__(
            instructions=(
                "You are Sarah, a helpful voice agent for American Fleet Services (AFS).\n"
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
                "- Never answer general knowledge or trivia. If asked unrelated questions, refuse briefly and immediately redirect to roadside assistance.\n"
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
        self._did_phone_greeting = False

    def _get_session_room(self) -> rtc.Room | None:
        """Safely fetch the active rtc.Room for this session.

        Reason: AgentSession exposes the active room via `session.room_io.room`
        (not `session.room`). Accessing `session.room_io` can raise when the
        session wasn't started with a room (tests/console).
        """

        try:
            room_io = self.session.room_io
        except Exception:
            return None

        room = getattr(room_io, "room", None)
        return room if isinstance(room, rtc.Room) else None

    def _get_session_room_io_subscribed_fut(self) -> asyncio.Future[None] | None:
        """Best-effort handle to the RoomIO audio subscription future."""

        try:
            room_io = self.session.room_io
        except Exception:
            return None

        subscribed = getattr(room_io, "subscribed_fut", None)
        return subscribed if isinstance(subscribed, asyncio.Future) else None

    @staticmethod
    def _is_sip_participant(participant: object) -> bool:
        return (
            getattr(participant, "kind", None)
            == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
        )

    def _build_phone_greeting(self, *, first_name: str | None, caller_phone: str | None) -> str:
        operator_name = os.getenv("AGENT_OPERATOR_NAME", "").strip() or "Sarah"
        company = os.getenv("AGENT_COMPANY_NAME", "").strip() or "AFS"

        phone = caller_phone.strip() if isinstance(caller_phone, str) and caller_phone.strip() else None

        if isinstance(first_name, str) and first_name.strip():
            name = first_name.strip()
            if phone:
                return (
                    f"Say exactly: Hello {name}, this is {operator_name} from {company}. "
                    f"I have your number as {phone}. Is this still the best number to reach you?"
                )
            return (
                f"Say exactly: Hello {name}, this is {operator_name} from {company}. "
                "Is this still the best number to reach you?"
            )

        return f"Say exactly: Hello, this is {operator_name} from {company}. How can I help you today?"

    def _refresh_sip_phone_number_from_room(self) -> None:
        """Best-effort extraction of caller ID from the active room.

        Reason: For telephony dispatch, the SIP participant can join slightly
        after the agent starts; extracting once in entrypoint can race.
        """

        if isinstance(self._sip_phone_number, str) and self._sip_phone_number.strip():
            return

        room = self._get_session_room()
        if room is None:
            return

        for participant in room.remote_participants.values():
            if not self._is_sip_participant(participant):
                continue

            attrs = participant.attributes or {}
            phone = attrs.get("sip.phoneNumber")
            if isinstance(phone, str) and phone.strip():
                self._sip_phone_number = phone.strip()
                return

            identity = getattr(participant, "identity", "")
            if isinstance(identity, str):
                candidate = identity.strip()
                if candidate.startswith("+") and candidate[1:].isdigit():
                    self._sip_phone_number = candidate
                    return

                match = re.search(r"(\+\d{8,15})", candidate)
                if match:
                    self._sip_phone_number = match.group(1)
                    return

    async def _wait_for_room_audio_subscription(self, timeout_s: float) -> None:
        fut = self._get_session_room_io_subscribed_fut()
        if fut is None or fut.done():
            return

        try:
            await asyncio.wait_for(asyncio.shield(fut), timeout=timeout_s)
        except TimeoutError:
            logger.warning("timed out waiting for room audio subscription on enter")

    async def _wait_for_sip_participant(self, room: rtc.Room, timeout_s: float) -> object | None:
        for participant in room.remote_participants.values():
            if self._is_sip_participant(participant):
                return participant

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[object] = loop.create_future()

        def _on_connected(participant: object) -> None:
            if self._is_sip_participant(participant) and not fut.done():
                fut.set_result(participant)

        room.on("participant_connected", _on_connected)
        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        except TimeoutError:
            return None
        finally:
            try:
                room.off("participant_connected", _on_connected)
            except Exception:
                pass

    async def on_enter(self) -> None:
        """Greet inbound SIP callers immediately, using caller ID lookup when possible."""

        # Avoid running the greeting in unit tests that use a bare AgentSession()
        # (no LLM configured). If tests want to validate greeting behavior they
        # can patch `session.generate_reply`, in which case this check won't skip.
        llm = getattr(self.session, "llm", None)
        if llm is None:
            generate_reply = getattr(self.session, "generate_reply", None)
            bound_func = getattr(generate_reply, "__func__", None)
            original = getattr(type(self.session), "generate_reply", None)
            if bound_func is not None and bound_func is original:
                return

        if self._did_phone_greeting:
            return

        # We only auto-greet inbound phone calls.
        # Reason: Avoid surprising behavior in non-telephony contexts (console/dev/tests).
        room = self._get_session_room()
        has_room = room is not None
        if not has_room and not (isinstance(self._sip_phone_number, str) and self._sip_phone_number.strip()):
            return

        if has_room and room is not None:
            # Ensure the caller can actually hear the first greeting.
            await self._wait_for_room_audio_subscription(timeout_s=15.0)

            sip_participant = await self._wait_for_sip_participant(room, timeout_s=15.0)
            if sip_participant is None:
                # Not a telephony call (no SIP participant); don't greet.
                return

            # Best-effort wait: SIP participant attributes can arrive just after connection.
            for _ in range(50):
                self._refresh_sip_phone_number_from_room()
                if isinstance(self._sip_phone_number, str) and self._sip_phone_number.strip():
                    break
                await asyncio.sleep(0.1)

        caller_phone = self._sip_phone_number.strip() if isinstance(self._sip_phone_number, str) else None
        if not caller_phone and has_room and room is not None:
            has_sip_participant = any(
                self._is_sip_participant(p)
                for p in room.remote_participants.values()
            )
            if has_sip_participant:
                self._did_phone_greeting = True
                self.session.generate_reply(
                    instructions=self._build_phone_greeting(first_name=None, caller_phone=None),
                    # Reason: Prevent echo/false barge-ins from cutting off the initial greeting.
                    allow_interruptions=False,
                )
            return

        if not caller_phone:
            return

        first_name: str | None = None
        try:
            # Reason: Warm the backend session using the caller ID so we can greet by name.
            # Use whitespace so `get_case_status` treats it as "no user message" and doesn't run extractors.
            case_status = await self._call_backend_tool(
                tool_name="get_case_status",
                tool_arguments={"last_user_message": " "},
            )
        except BackendToolsClientError:
            self._did_phone_greeting = True
            self.session.generate_reply(
                instructions=self._build_phone_greeting(first_name=None, caller_phone=caller_phone),
                # Reason: Prevent echo/false barge-ins from cutting off the initial greeting.
                allow_interruptions=False,
            )
            return

        customer = case_status.get("customer") if isinstance(case_status, dict) else None
        if isinstance(customer, dict):
            candidate = customer.get("first_name")
            if isinstance(candidate, str) and candidate.strip():
                first_name = candidate.strip()

        self._did_phone_greeting = True
        self.session.generate_reply(
            instructions=self._build_phone_greeting(first_name=first_name, caller_phone=caller_phone),
            # Reason: Prevent echo/false barge-ins from cutting off the initial greeting.
            allow_interruptions=False,
        )

    @property
    def call_id(self) -> str:
        room = self._get_session_room()
        if room is not None:
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
