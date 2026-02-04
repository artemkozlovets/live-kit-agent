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

from livekit_agent.backend_tools_client import BackendToolsClientError, BookingNotConfirmedError
from livekit_agent.tools import load_tool_schemas

logger = logging.getLogger("livekit-agent.openai-realtime")


_PHONE_AFTER_LABEL_RE = re.compile(
    r"\b(?:phone(?:\s+number)?|callback(?:\s+number)?)\s*(?:is|:)\s*([+0-9][0-9\s\-\(\)]{8,}[0-9])",
    flags=re.IGNORECASE,
)
_PHONE_ANYWHERE_RE = re.compile(r"(\+?\d[\d\s\-\(\)]{8,}\d)")

_SPANISH_REQUEST_RE = re.compile(r"\b(?:spanish|español|espanol)\b", flags=re.IGNORECASE)
_ENGLISH_REQUEST_RE = re.compile(r"\b(?:english|inglés|ingles)\b", flags=re.IGNORECASE)
_SAY_EXACTLY_PREFIX_RE = re.compile(r"^\s*say\s+exactly\s*:\s*", flags=re.IGNORECASE)

_SPANISH_HINT_WORDS: frozenset[str] = frozenset(
    {
        "hola",
        "buenos",
        "buenas",
        "gracias",
        "por",
        "favor",
        "necesito",
        "ayuda",
        "mi",
        "nombre",
        "es",
        "estoy",
        "tengo",
        "quiero",
        "porfavor",
        "aqui",
        "aquí",
        "si",
        "sí",
        "claro",
    }
)


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _strip_say_exactly_prefix(value: str) -> str:
    return _SAY_EXACTLY_PREFIX_RE.sub("", value or "").strip()


def _normalize_transcript_for_comparison(value: str) -> str:
    """Normalize text for best-effort equality checks.

    Reason: Realtime transcripts can differ slightly from the original text (punctuation,
    spacing). For echo detection we only need a stable comparison key.
    """

    lowered = (value or "").casefold()
    lowered = re.sub(r"[^a-z0-9+]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


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


def _normalize_language_text(text: str) -> str:
    # Reason: stable normalization for language/yes-no intent checks.
    lowered = text.casefold()
    lowered = lowered.replace("¿", " ").replace("¡", " ")
    lowered = re.sub(r"[^a-z0-9áéíóúñü\s]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _looks_like_spanish(text: str, *, language_hint: str | None = None) -> bool:
    if isinstance(language_hint, str) and language_hint.strip().casefold().startswith("es"):
        return True

    normalized = _normalize_language_text(text)
    if not normalized:
        return False

    if any(ch in text for ch in ("¿", "¡", "ñ", "á", "é", "í", "ó", "ú", "ü")):
        # If we see Spanish punctuation/diacritics, a single hint word is enough.
        tokens = set(normalized.split())
        return bool(tokens & _SPANISH_HINT_WORDS)

    tokens = set(normalized.split())
    # Heuristic: require multiple common Spanish tokens to reduce false positives.
    return len(tokens & _SPANISH_HINT_WORDS) >= 2


def _language_choice(text: str) -> str | None:
    """Return 'es' or 'en' if the user is clearly choosing a language."""

    normalized = _normalize_language_text(text)
    if not normalized:
        return None

    if _SPANISH_REQUEST_RE.search(normalized):
        return "es"
    if _ENGLISH_REQUEST_RE.search(normalized):
        return "en"

    # Short confirmations in Spanish/English.
    if normalized in {"si", "sí", "claro", "ok", "okay", "yes", "yeah", "yep", "sure"}:
        return "es"
    if normalized in {"no", "nope"}:
        return "en"

    return None


def _looks_like_language_control_message(text: str) -> bool:
    # Reason: avoid calling the backend on "language selection" turns.
    normalized = _normalize_language_text(text)
    if not normalized:
        return False

    if normalized in {"si", "sí", "claro", "ok", "okay", "yes", "yeah", "yep", "sure", "no", "nope"}:
        return True

    # If the message mentions a language but is otherwise just filler words, treat it as
    # a language-only control message (e.g., "Can we do this in Spanish?").
    if not (_SPANISH_REQUEST_RE.search(normalized) or _ENGLISH_REQUEST_RE.search(normalized)):
        return False

    tokens = normalized.split()
    stopwords: set[str] = {
        "a",
        "an",
        "and",
        "can",
        "could",
        "do",
        "does",
        "english",
        "espanol",
        "español",
        "in",
        "ingles",
        "inglés",
        "let",
        "lets",
        "me",
        "no",
        "please",
        "por",
        "favor",
        "podemos",
        "podria",
        "podría",
        "puede",
        "puedes",
        "speak",
        "spanish",
        "talk",
        "this",
        "to",
        "us",
        "we",
        "with",
        "would",
        "you",
        "yo",
        "quiero",
        "hablar",
        "en",
    }

    remaining = [t for t in tokens if t not in stopwords]
    return not remaining


def _combine_instructions(*parts: str | None) -> str | None:
    cleaned: list[str] = []
    for part in parts:
        if not isinstance(part, str):
            continue
        stripped = part.strip()
        if stripped:
            cleaned.append(stripped)
    return "\n\n".join(cleaned) if cleaned else None


def _recap_policy_instructions(case_status: object) -> str | None:
    if not isinstance(case_status, dict):
        return None

    current_phase = case_status.get("current_phase")
    phase = current_phase.strip().lower() if isinstance(current_phase, str) else ""
    if phase == "booking":
        booking_status = None
        booking_payload = case_status.get("booking")
        if isinstance(booking_payload, dict):
            status = booking_payload.get("status")
            if isinstance(status, str) and status.strip():
                booking_status = status.strip().lower()

        if booking_status == "confirmed":
            return (
                "Recap policy (post-confirmation): Do NOT repeat back any details (name, phone, address, vehicle, location). "
                "Do NOT ask for confirmation again. Proceed with the service order."
            )

        message_category = case_status.get("message_category")
        category = message_category.strip().lower() if isinstance(message_category, str) else ""
        if category in {"confirmation", "decline"}:
            return (
                "Recap policy (booking response): Do NOT repeat back details or do another recap. "
                "If the caller confirmed, proceed. If the caller declined, ask what needs to change."
            )

        return (
            "Recap policy (booking): Give ONE concise recap of the service + location + vehicle only (do not read back contact details), "
            "then ask for an explicit yes/no."
        )

    return (
        "Recap policy (pre-booking): Do NOT repeat back the caller's provided details (name, phone, email, address, vehicle, location). "
        "Acknowledge briefly (e.g., “Got it”) and ask the next missing item."
    )


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
                "Language:\n"
                "- Speak English by default.\n"
                "- Only switch to Spanish after the caller confirms they want Spanish.\n"
                "- Once a language is chosen, stick to it.\n"
                "\n"
                "Conversation style:\n"
                "- The caller may give a large info-dump (name, phone, address, etc.) in any order.\n"
                "- Extract everything you can from each turn.\n"
                "- Avoid repetition: do not read back the caller's details during slot-filling. Only do a single recap of service+location+vehicle, right before booking confirmation.\n"
                "- Do NOT ask rigid one-by-one questions. If multiple things are missing, ask for them together.\n"
                "- If the caller says 'start over' / 'throw away that info', discard the previously collected details and continue fresh.\n"
                "\n"
                "Tools:\n"
                "- Use tools to validate and save customer data (validate_phone, check_customer, register_new_customer, update_customer, etc.).\n"
                "- When you have a phone number, call validate_phone and then check_customer. Do not claim you are \"checking\" unless you actually called the tool.\n"
                "- Booking safety: do NOT call store_service_order until the caller has explicitly confirmed (yes/no). After a clear \"yes\", call confirm_services, then call store_service_order.\n"
                "- Prefer saving in as few tool calls as possible once you have enough information.\n"
                "- If the caller provides the vehicle make/model (ex: \"Ford F-150\"), save it on the service (vehicle_make/vehicle_model) so it can be stored in the database.\n"
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
                "- Only ask for fields that are explicitly listed in case_status.missing_fields. Do not re-ask for name/phone if case_status.customer already has them.\n"
                "- The backend guidance JSON may include `customer_known_data` (PII). Use it only for tool arguments and never read it to the caller.\n"
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
        self._realtime_pending_user_text_parts: list[str] = []
        self._realtime_pending_last_transcript_created_at_unix_s = 0.0
        self._realtime_pending_task: asyncio.Task[None] | None = None
        self._last_user_state: str | None = None
        self._last_user_state_changed_at_wallclock_unix_s = 0.0
        self._user_state_change_event = asyncio.Event()
        self._preferred_language: str = "en"
        self._language_offer_pending = False
        self._last_user_input_language: str | None = None
        self._phone_greeting_expected_transcript_norm: str | None = None
        self._phone_greeting_expected_set_at_wallclock_unix_s = 0.0

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

    def _language_lock_instructions(self) -> str:
        if self._preferred_language == "es":
            return "Language:\n- Speak Spanish only."
        return "Language:\n- Speak English only."

    def _maybe_offer_spanish_instructions(self, user_text: str) -> str | None:
        if self._preferred_language != "en":
            return None
        if self._language_offer_pending:
            return None
        if not _looks_like_spanish(user_text, language_hint=self._last_user_input_language):
            return None

        # Reason: Avoid auto-switching languages. Ask once, then only switch after confirmation.
        self._language_offer_pending = True
        return 'Also ask: "Would you prefer to speak in Spanish?" (Do not switch unless the caller confirms.)'

    def _language_confirmation_instructions(self, *, language: str) -> str:
        if language == "es":
            return (
                'Say exactly: Perfecto — hablemos en español. '
                "Si prefieres inglés, solo dime “English”."
            )
        return (
            "Say exactly: No problem — we can continue in English. "
            "If you'd prefer Spanish, just say “Spanish”."
        )

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

        def _on_user_state_changed(ev: Any) -> None:
            try:
                new_state = getattr(ev, "new_state", None)
                if not isinstance(new_state, str):
                    return
                self._last_user_state = new_state
                self._last_user_state_changed_at_wallclock_unix_s = time.time()
                self._user_state_change_event.set()
            except Exception:
                logger.exception("user_state_changed handler failed")

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

                greeting_norm = self._phone_greeting_expected_transcript_norm
                if greeting_norm:
                    if (time.time() - self._phone_greeting_expected_set_at_wallclock_unix_s) > 20.0:
                        self._phone_greeting_expected_transcript_norm = None
                        self._phone_greeting_expected_set_at_wallclock_unix_s = 0.0
                    else:
                        transcript_norm = _normalize_transcript_for_comparison(transcript)
                        if transcript_norm == greeting_norm:
                            # Reason: If the caller is on speakerphone, the agent's own uninterruptible greeting
                            # can be picked up and transcribed as user input, leading to "talking to itself".
                            return
                        self._phone_greeting_expected_transcript_norm = None
                        self._phone_greeting_expected_set_at_wallclock_unix_s = 0.0

                if created_at_unix_s:
                    self._last_final_transcript_unix_s = created_at_unix_s

                language = getattr(ev, "language", None)
                if isinstance(language, str) and language.strip():
                    self._last_user_input_language = language.strip().casefold()

                self._queue_realtime_user_text_turn(user_text=transcript, created_at_unix_s=created_at_unix_s)
            except Exception:
                logger.exception("user_input_transcribed handler failed")

        def _on_close(_: Any) -> None:
            try:
                self._cancel_pending_realtime_user_text_turn()
            except Exception:
                logger.exception("close handler failed")

        self.session.on("close", _on_close)
        self.session.on("user_state_changed", _on_user_state_changed)
        self.session.on("user_input_transcribed", _on_user_input_transcribed)

    @staticmethod
    def _log_task_exception(task: asyncio.Task[object]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("realtime turn handler task failed")

    def _queue_realtime_user_text_turn(self, *, user_text: str, created_at_unix_s: float) -> None:
        user_text = user_text.strip()
        if not user_text:
            return

        last = self._realtime_pending_user_text_parts[-1] if self._realtime_pending_user_text_parts else ""
        if last != user_text:
            self._realtime_pending_user_text_parts.append(user_text)
        self._realtime_pending_last_transcript_created_at_unix_s = created_at_unix_s

        if self._realtime_pending_task is not None and not self._realtime_pending_task.done():
            self._realtime_pending_task.cancel()

        task = asyncio.create_task(
            self._maybe_handle_realtime_user_text_turn(expected_created_at_unix_s=created_at_unix_s)
        )
        task.add_done_callback(self._log_task_exception)
        self._realtime_pending_task = task

    def _cancel_pending_realtime_user_text_turn(self) -> None:
        if self._realtime_pending_task is not None and not self._realtime_pending_task.done():
            self._realtime_pending_task.cancel()
        self._realtime_pending_task = None
        self._realtime_pending_user_text_parts.clear()
        self._realtime_pending_last_transcript_created_at_unix_s = 0.0

    async def _maybe_handle_realtime_user_text_turn(self, *, expected_created_at_unix_s: float) -> None:
        """Trigger our backend-first turn loop from Realtime transcripts (debounced).

        Reason: When using a Realtime model with server-side turn detection enabled, the
        LiveKit Agents SDK does not call `on_user_turn_completed` for audio turns. If we also
        disable the model's automatic response creation (`create_response=false`), we must
        manually trigger the next reply.
        """

        # Give the SDK a chance to call `on_user_turn_completed` (in configs where it applies),
        # and debounce bursts of final transcripts that happen before the end of a real turn.
        debounce_s = 0.25
        raw_debounce = os.getenv("REALTIME_TRANSCRIPT_DEBOUNCE_S", "").strip()
        if raw_debounce:
            try:
                debounce_s = max(0.05, float(raw_debounce))
            except ValueError:
                logger.warning("Invalid REALTIME_TRANSCRIPT_DEBOUNCE_S=%r (expected float); using default", raw_debounce)
        await asyncio.sleep(debounce_s)

        if expected_created_at_unix_s != self._realtime_pending_last_transcript_created_at_unix_s:
            return

        if expected_created_at_unix_s and self._last_user_turn_hook_created_at_unix_s >= expected_created_at_unix_s:
            self._realtime_pending_user_text_parts.clear()
            self._realtime_pending_last_transcript_created_at_unix_s = 0.0
            self._realtime_pending_task = None
            return

        if not expected_created_at_unix_s and (time.time() - self._last_user_turn_hook_wallclock_unix_s) < 0.25:
            self._realtime_pending_user_text_parts.clear()
            self._realtime_pending_last_transcript_created_at_unix_s = 0.0
            self._realtime_pending_task = None
            return

        # Avoid speaking while the caller is still talking. Realtime transcripts can be finalized
        # mid-turn, so we wait for a stable "listening" state before triggering the reply.
        quiet_s = 0.3
        raw_quiet = os.getenv("REALTIME_TRANSCRIPT_POST_SILENCE_S", "").strip()
        if raw_quiet:
            try:
                quiet_s = max(0.0, float(raw_quiet))
            except ValueError:
                logger.warning(
                    "Invalid REALTIME_TRANSCRIPT_POST_SILENCE_S=%r (expected float); using default", raw_quiet
                )

        max_wait_s = 8.0
        raw_max_wait = os.getenv("REALTIME_TRANSCRIPT_MAX_WAIT_S", "").strip()
        if raw_max_wait:
            try:
                max_wait_s = max(0.5, float(raw_max_wait))
            except ValueError:
                logger.warning("Invalid REALTIME_TRANSCRIPT_MAX_WAIT_S=%r (expected float); using default", raw_max_wait)

        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            if expected_created_at_unix_s != self._realtime_pending_last_transcript_created_at_unix_s:
                return

            if self._last_user_state != "speaking":
                stable_for_s = time.time() - self._last_user_state_changed_at_wallclock_unix_s
                if stable_for_s >= quiet_s:
                    break

            self._user_state_change_event.clear()
            try:
                await asyncio.wait_for(self._user_state_change_event.wait(), timeout=0.25)
            except TimeoutError:
                pass

        if expected_created_at_unix_s != self._realtime_pending_last_transcript_created_at_unix_s:
            return

        user_text = " ".join(self._realtime_pending_user_text_parts).strip()
        self._realtime_pending_user_text_parts.clear()
        self._realtime_pending_last_transcript_created_at_unix_s = 0.0
        self._realtime_pending_task = None

        await self._handle_realtime_user_text_turn(user_text)

    async def _handle_user_text_turn(
        self,
        *,
        user_text: str,
        turn_ctx: ChatContext,
        user_message_already_in_history: bool = False,
    ) -> None:
        if self._fatal_error:
            return

        user_text = user_text.strip()
        if not user_text:
            return

        normalized_for_lang = _normalize_language_text(user_text)
        has_language_keyword = bool(
            _SPANISH_REQUEST_RE.search(normalized_for_lang) or _ENGLISH_REQUEST_RE.search(normalized_for_lang)
        )

        if self._language_offer_pending or has_language_keyword:
            choice = _language_choice(user_text)
            if choice in {"en", "es"}:
                self._preferred_language = choice
                self._language_offer_pending = False

                if _looks_like_language_control_message(user_text):
                    self.session.generate_reply(
                        instructions=_combine_instructions(
                            self._language_lock_instructions(),
                            self._language_confirmation_instructions(language=choice),
                            "Do not call any tools.",
                        ),
                        allow_interruptions=False,
                    )
                    return

        language_instructions = _combine_instructions(
            self._language_lock_instructions(),
            self._maybe_offer_spanish_instructions(user_text),
        )

        has_llm = getattr(self.session, "llm", None) is not None
        should_include_user_input = not (user_message_already_in_history and has_llm)

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
                if should_include_user_input:
                    self.session.generate_reply(
                        user_input=user_text,
                        chat_ctx=turn_ctx,
                        instructions=_combine_instructions(
                            language_instructions,
                            f"Authoritative tool results (JSON): {payload_json}",
                        ),
                    )
                else:
                    self.session.generate_reply(
                        chat_ctx=turn_ctx,
                        instructions=_combine_instructions(
                            language_instructions,
                            f"Authoritative tool results (JSON): {payload_json}",
                        ),
                    )
            else:
                if should_include_user_input:
                    self.session.generate_reply(
                        user_input=user_text,
                        chat_ctx=turn_ctx,
                        instructions=language_instructions,
                    )
                else:
                    self.session.generate_reply(
                        chat_ctx=turn_ctx,
                        instructions=language_instructions,
                    )
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
        if should_include_user_input:
            self.session.generate_reply(
                user_input=user_text,
                chat_ctx=turn_ctx,
                instructions=_combine_instructions(
                    language_instructions,
                    _recap_policy_instructions(case_status),
                    f"Authoritative backend guidance (JSON): {payload_json}",
                ),
            )
        else:
            self.session.generate_reply(
                chat_ctx=turn_ctx,
                instructions=_combine_instructions(
                    language_instructions,
                    _recap_policy_instructions(case_status),
                    f"Authoritative backend guidance (JSON): {payload_json}",
                ),
            )

    async def _handle_realtime_user_text_turn(self, user_text: str) -> None:
        async with self._realtime_turn_lock:
            await self._handle_user_text_turn(
                user_text=user_text,
                turn_ctx=ChatContext(),
                user_message_already_in_history=True,
            )

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
                greeting = self._build_phone_greeting(first_name=None, caller_phone=None)
                self._phone_greeting_expected_transcript_norm = _normalize_transcript_for_comparison(
                    _strip_say_exactly_prefix(greeting)
                )
                self._phone_greeting_expected_set_at_wallclock_unix_s = time.time()
                self._did_phone_greeting = True
                self.session.generate_reply(
                    instructions=_combine_instructions(
                        self._language_lock_instructions(),
                        greeting,
                    ),
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
            greeting = self._build_phone_greeting(first_name=None, caller_phone=caller_phone)
            self._phone_greeting_expected_transcript_norm = _normalize_transcript_for_comparison(
                _strip_say_exactly_prefix(greeting)
            )
            self._phone_greeting_expected_set_at_wallclock_unix_s = time.time()
            self._did_phone_greeting = True
            self.session.generate_reply(
                instructions=_combine_instructions(
                    self._language_lock_instructions(),
                    greeting,
                ),
                # Reason: Prevent echo/false barge-ins from cutting off the initial greeting.
                allow_interruptions=False,
            )
            return

        customer = case_status.get("customer") if isinstance(case_status, dict) else None
        if isinstance(customer, dict):
            candidate = customer.get("first_name")
            if isinstance(candidate, str) and candidate.strip():
                first_name = candidate.strip()

        greeting = self._build_phone_greeting(first_name=first_name, caller_phone=caller_phone)
        self._phone_greeting_expected_transcript_norm = _normalize_transcript_for_comparison(
            _strip_say_exactly_prefix(greeting)
        )
        self._phone_greeting_expected_set_at_wallclock_unix_s = time.time()
        self._did_phone_greeting = True
        self.session.generate_reply(
            instructions=_combine_instructions(
                self._language_lock_instructions(),
                greeting,
            ),
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
        self._cancel_pending_realtime_user_text_turn()

        created_at = getattr(new_message, "created_at", None)
        if isinstance(created_at, (int, float)):
            self._last_user_turn_hook_created_at_unix_s = float(created_at)
        else:
            self._last_user_turn_hook_created_at_unix_s = time.time()
        self._last_user_turn_hook_wallclock_unix_s = time.time()

        user_text = getattr(new_message, "text_content", None) or ""
        user_message_already_in_history = getattr(self.session, "llm", None) is not None
        await self._handle_user_text_turn(
            user_text=user_text,
            turn_ctx=turn_ctx,
            user_message_already_in_history=user_message_already_in_history,
        )

    async def forward_tool(self, *, tool_name: str, tool_arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle local tools and forward the rest to backend `/tools` API (v2)."""

        if tool_name == "transfer_to_human":
            return await self._transfer_to_human()

        try:
            return await self._backend.call_tool(
                call_id=self.call_id,
                sip_phone_number=self._sip_phone_number,
                confirmed_callback_number=self._confirmed_callback_number,
                assistant_variable_values=self._assistant_variable_values,
                tool_call_id=f"tool-{uuid.uuid4().hex}",
                tool_name=tool_name,
                tool_arguments=tool_arguments,
            )
        except BookingNotConfirmedError as exc:
            # Reason: Booking confirmation failures are expected policy rejections. Return a structured
            # tool result so the model can recover instead of seeing a generic "internal error".
            return {
                "success": False,
                "error": str(exc) or "User has not explicitly confirmed the booking.",
                "next_action": (
                    "Ask the caller for an explicit yes/no confirmation. "
                    "If yes: call confirm_services, then call store_service_order. "
                    "If no: ask what needs to change, then call update_service_order."
                ),
            }
        except BackendToolsClientError as exc:
            logger.warning(
                "backend tool call failed",
                extra={
                    "tool_name": tool_name,
                    "error_type": type(exc).__name__,
                },
                exc_info=exc,
            )
            return {
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
                "next_action": "Tell the caller there was a system issue and try again.",
            }

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
