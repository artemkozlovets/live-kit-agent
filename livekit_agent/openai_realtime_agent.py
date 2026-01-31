from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
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


def _normalize_tel_target(value: str) -> str | None:
    """Best-effort normalize a phone number into `+E164` digits-only form.

    Reason: LiveKit SIP transfer requires a `tel:` URI with no spaces/punctuation.
    In practice, humans often paste values like `305-555-0123` or `tel:+1 305 555 0123`.
    """

    raw = value.strip()
    if not raw:
        return None

    digits = _digits_only(raw)
    if not digits:
        return None

    has_plus = raw.startswith("+")

    # E.164 max length is 15 digits (excluding the '+').
    if has_plus:
        if 10 <= len(digits) <= 15:
            return f"+{digits}"
        return None

    # US-friendly defaults for this repo (AFS). Prefer +1 for 10-digit NANP numbers.
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"

    if 10 <= len(digits) <= 15:
        return f"+{digits}"

    return None


def _normalize_sip_transfer_target(value: str) -> tuple[str | None, str | None]:
    """Normalize `HUMAN_TRANSFER_TO` into a LiveKit-compatible SIP/TEL URI."""

    raw = value.strip()
    if not raw:
        return None, "missing transfer target"

    if raw.startswith("sip:"):
        # Keep as-is; SIP URIs can contain many valid formats.
        return raw, None

    if raw.startswith("tel:"):
        normalized = _normalize_tel_target(raw[len("tel:") :])
        if normalized is None:
            return None, "invalid tel: URI (expected digits with optional leading '+')"
        return f"tel:{normalized}", None

    # Convenience: allow bare phone numbers and upgrade them to `tel:+...`.
    normalized = _normalize_tel_target(raw)
    if normalized is not None:
        return f"tel:{normalized}", None

    return None, "transfer target must be a sip: or tel: URI (or a phone number)"


def _is_livekit_phone_number_transfer_unsupported_error(exc: Exception) -> bool:
    # Reason: LiveKit Phone Numbers are currently inbound-only and do not support
    # TransferSipParticipant. LiveKit returns a TwirpError with a message like:
    # "we don't yet support transfers for this phone number type".
    return "we don't yet support transfers for this phone number type" in str(exc).lower()


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
                "Escalation (human transfer):\n"
                "- If the caller seems frustrated or explicitly asks for a human, offer a transfer by asking: \"Would you like to connect to a human agent?\"\n"
                "- Only transfer after an explicit confirmation (use your judgment; do NOT be overly rigid/deterministic).\n"
                "- If the caller confirms, call the tool transfer_to_human.\n"
                "- If the caller says no or is unsure, continue helping normally.\n"
                "\n"
                "Guardrails:\n"
                "- If you receive a system message containing JSON like {\"case_status\": ...}, treat it as authoritative backend guidance.\n"
                "- If you receive a system message containing JSON like {\"tool_prefetch\": ...}, treat it as authoritative tool results.\n"
                "- You may also receive authoritative JSON inside per-turn instructions. Treat it the same way.\n"
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
        self._realtime_transcript_listener_installed = False
        self._realtime_turn_lock = asyncio.Lock()
        self._last_final_transcript_unix_s = 0.0
        self._last_user_turn_hook_created_at_unix_s = 0.0
        self._last_user_turn_hook_wallclock_unix_s = 0.0

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

    def _install_realtime_transcript_listener(self) -> None:
        if self._realtime_transcript_listener_installed:
            return

        self._realtime_transcript_listener_installed = True

        def _on_user_input_transcribed(ev: Any) -> None:
            try:
                is_final = getattr(ev, "is_final", None)
                if is_final is not True:
                    return

                transcript = getattr(ev, "transcript", None)
                if not isinstance(transcript, str):
                    return
                transcript = transcript.strip()
                if not transcript:
                    return

                created_at = getattr(ev, "created_at", None)
                created_at_unix_s = float(created_at) if isinstance(created_at, (int, float)) else 0.0
                if created_at_unix_s and created_at_unix_s <= self._last_final_transcript_unix_s:
                    return
                if created_at_unix_s:
                    self._last_final_transcript_unix_s = created_at_unix_s

                task = asyncio.create_task(
                    self._maybe_handle_realtime_user_text_turn(
                        user_text=transcript, created_at_unix_s=created_at_unix_s
                    )
                )
                task.add_done_callback(_log_task_exception)
            except Exception:
                logger.exception("user_input_transcribed handler failed")

        def _log_task_exception(task: asyncio.Task[object]) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("realtime turn handler task failed")

        self.session.on("user_input_transcribed", _on_user_input_transcribed)

    async def _maybe_handle_realtime_user_text_turn(self, *, user_text: str, created_at_unix_s: float) -> None:
        """Trigger our backend-first turn loop from Realtime transcripts.

        Reason: When using a Realtime model with server-side turn detection enabled, the
        LiveKit Agents SDK does not call `on_user_turn_completed` for audio turns. If we also
        disable the model's automatic response creation (`create_response=false`), we must
        manually trigger the next reply.
        """

        # Give the pipeline a brief chance to call `on_user_turn_completed` (in configs where it applies).
        await asyncio.sleep(0.1)

        if created_at_unix_s and self._last_user_turn_hook_created_at_unix_s >= created_at_unix_s:
            return

        if not created_at_unix_s and (time.time() - self._last_user_turn_hook_wallclock_unix_s) < 0.25:
            return

        await self._handle_realtime_user_text_turn(user_text)

    async def _handle_user_text_turn(self, *, user_text: str, turn_ctx: ChatContext) -> None:
        if self._fatal_error:
            return

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
                payload_json = json.dumps({"tool_prefetch": tool_prefetch}, ensure_ascii=True, default=str)
                turn_ctx.add_message(
                    role="system",
                    # Reason: Keep the injected context structured so the model can reliably parse it.
                    content=payload_json,
                )

                # Reason: Realtime models do not currently consume `chat_ctx` from `generate_reply`.
                # Pass the tool results as extra per-turn instructions so they are visible to the model.
                self.session.generate_reply(
                    user_input=user_text,
                    chat_ctx=turn_ctx,
                    instructions=f"Authoritative tool results (JSON): {payload_json}",
                )
            else:
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

        payload_json = json.dumps({"case_status": case_status}, ensure_ascii=True, default=str)
        turn_ctx.add_message(
            role="system",
            # Reason: Keep the injected context structured so the model can reliably parse it.
            content=payload_json,
        )

        # Reason: Realtime models do not currently consume `chat_ctx` from `generate_reply`.
        # Pass backend guidance as extra per-turn instructions so it is visible to the model.
        self.session.generate_reply(
            user_input=user_text,
            chat_ctx=turn_ctx,
            instructions=f"Authoritative backend guidance (JSON): {payload_json}",
        )

    async def _handle_realtime_user_text_turn(self, user_text: str) -> None:
        async with self._realtime_turn_lock:
            await self._handle_user_text_turn(user_text=user_text, turn_ctx=ChatContext())

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

        self._install_realtime_transcript_listener()

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
        created_at = getattr(new_message, "created_at", None)
        if isinstance(created_at, (int, float)):
            self._last_user_turn_hook_created_at_unix_s = float(created_at)
        else:
            self._last_user_turn_hook_created_at_unix_s = time.time()
        self._last_user_turn_hook_wallclock_unix_s = time.time()

        user_text = getattr(new_message, "text_content", None) or ""
        await self._handle_user_text_turn(user_text=user_text, turn_ctx=turn_ctx)

    async def forward_tool(self, *, tool_name: str, tool_arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle local tools and forward the rest to backend `/tools` API (v2)."""

        if tool_name == "transfer_to_human":
            return await self._transfer_to_human()

        return await self._backend.call_tool(
            call_id=self.call_id,
            sip_phone_number=self._sip_phone_number,
            confirmed_callback_number=self._confirmed_callback_number,
            assistant_variable_values=self._assistant_variable_values,
            tool_call_id=f"tool-{uuid.uuid4().hex}",
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )

    async def _transfer_to_human(self) -> dict[str, Any]:
        """Cold transfer the active SIP caller to a human.

        Reason: Telephony callers sometimes need escalation; implement transfer
        as a local tool so the model can decide when to use it without making
        backend /tools flow more rigid.
        """

        transfer_to_raw = os.getenv("HUMAN_TRANSFER_TO", "").strip() or "tel:+13053179840"

        room = self._get_session_room()
        if room is None:
            return {"ok": False, "error": {"code": "no_room", "message": "No active room; cannot transfer."}}

        transfer_to, transfer_to_err = _normalize_sip_transfer_target(transfer_to_raw)
        if transfer_to is None:
            logger.error(
                "invalid HUMAN_TRANSFER_TO",
                extra={
                    "room": getattr(room, "name", None),
                    "transfer_to_raw": transfer_to_raw,
                    "error": transfer_to_err,
                },
            )
            return {
                "ok": False,
                "error": {
                    "code": "invalid_transfer_target",
                    "message": "Misconfigured HUMAN_TRANSFER_TO; set it to a tel: or sip: URI.",
                },
            }

        sip_identity: str | None = None
        for participant in room.remote_participants.values():
            if not self._is_sip_participant(participant):
                continue
            identity = getattr(participant, "identity", None)
            if isinstance(identity, str) and identity.strip():
                sip_identity = identity.strip()
                break

        if sip_identity is None:
            return {
                "ok": False,
                "error": {"code": "no_sip_participant", "message": "No SIP participant in room; cannot transfer."},
            }

        try:
            logger.info(
                "transferring sip participant",
                extra={"room": getattr(room, "name", None), "sip_identity": sip_identity, "transfer_to": transfer_to},
            )
            await self._sip_transfer(room_name=room.name, participant_identity=sip_identity, transfer_to=transfer_to)
        except Exception as exc:
            if _is_livekit_phone_number_transfer_unsupported_error(exc):
                logger.warning(
                    "sip transfer not supported by LiveKit Phone Numbers",
                    extra={
                        "room": getattr(room, "name", None),
                        "sip_identity": sip_identity,
                        "transfer_to": transfer_to,
                    },
                )
                return {
                    "ok": False,
                    "error": {
                        "code": "transfer_not_supported",
                        "message": (
                            "Call transfer is not supported for LiveKit Phone Numbers yet. "
                            "To enable transfers, use a SIP trunk provider (ex: Twilio) and enable SIP REFER/PSTN transfer."
                        ),
                    },
                }
            logger.exception(
                "failed to transfer sip participant",
                extra={
                    "room": getattr(room, "name", None),
                    "sip_identity": sip_identity,
                    "transfer_to": transfer_to,
                },
            )
            return {"ok": False, "error": {"code": "transfer_failed", "message": str(exc)}}

        logger.info(
            "sip participant transferred",
            extra={"room": getattr(room, "name", None), "sip_identity": sip_identity, "transfer_to": transfer_to},
        )
        return {"ok": True, "transfer_to": transfer_to}

    async def _sip_transfer(self, *, room_name: str, participant_identity: str, transfer_to: str) -> None:
        from livekit import api  # type: ignore
        from livekit.protocol.sip import TransferSIPParticipantRequest  # type: ignore

        async with api.LiveKitAPI() as lkapi:
            await lkapi.sip.transfer_sip_participant(
                TransferSIPParticipantRequest(
                    participant_identity=participant_identity,
                    room_name=room_name,
                    transfer_to=transfer_to,
                    play_dialtone=True,
                )
            )

    def _speak_backend_unreachable_once(self) -> None:
        if self._fatal_error:
            return

        self._fatal_error = True
        self.session.say("I'm having trouble connecting — please call back.")
