from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

# Load `.env` early so CLI options (LIVEKIT_*) and NUM_CPUS are available during
# `livekit.agents` import and initialization.
load_dotenv()
from livekit import rtc
from livekit.agents import Agent, AgentServer, AgentSession, ChatContext, JobContext, JobProcess, cli, function_tool
from livekit.agents.types import APIConnectOptions
from livekit.agents.voice.events import CloseEvent, ErrorEvent
from livekit.plugins import cartesia, deepgram, google, silero

from livekit_agent.backend_tools_client import BackendToolsClient, BackendToolsClientError
from livekit_agent.flow_controller import Action, FlowController, Phase, SpeakAction, ToolAction
from livekit_agent.session_report_publisher import SessionReportPublisher
from livekit_agent.tools import load_tool_schemas

logger = logging.getLogger("livekit-agent-vapi-adapter")

_INT_ENV_RE = re.compile(r"^\d+$")
_THEN_ACTION_FALLBACK_PROMPT = "Sorry — I'm having trouble. Could you describe what you need today?"
_AUTH_HEADER_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Common auth header patterns that can leak secrets into logs.
    (re.compile(r"(Authorization['\"]:\s*['\"]Token\s+)[^'\"]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Authorization['\"]:\s*['\"]Bearer\s+)[^'\"]+", re.IGNORECASE), r"\1***"),
)


def _redact_secrets(text: str) -> str:
    redacted = text
    for pattern, replacement in _AUTH_HEADER_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    if not _INT_ENV_RE.match(raw):
        logger.warning("Invalid %s=%r (expected int); ignoring", name, raw)
        return None
    return int(raw)


def _float_env(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r (expected float); ignoring", name, raw)
        return None


def _build_server() -> AgentServer:
    kwargs: dict[str, Any] = {}
    host = os.getenv("HOST", "").strip() or os.getenv("LIVEKIT_WORKER_HOST", "").strip()
    if host:
        kwargs["host"] = host

    port = _int_env("PORT") or _int_env("LIVEKIT_WORKER_PORT")
    if port is not None:
        kwargs["port"] = port

    prometheus_port = _int_env("PROMETHEUS_PORT") or _int_env("LIVEKIT_PROMETHEUS_PORT")
    if prometheus_port is not None:
        kwargs["prometheus_port"] = prometheus_port

    prometheus_multiproc_dir = (
        os.getenv("PROMETHEUS_MULTIPROC_DIR", "").strip()
        or os.getenv("LIVEKIT_PROMETHEUS_MULTIPROC_DIR", "").strip()
    )
    if prometheus_multiproc_dir:
        kwargs["prometheus_multiproc_dir"] = prometheus_multiproc_dir

    return AgentServer(**kwargs)


_AFFIRMATIVE_RE = re.compile(r"\b(yes|yeah|yep|correct|that's right|right|sure|ok|okay)\b", re.I)
_NEGATIVE_RE = re.compile(r"\b(no|nope|nah|negative|not really|wrong)\b", re.I)
_PHONE_RE = re.compile(r"(\+?\d[\d\-\(\)\s]{7,}\d)")
_SPOKEN_DIGIT_RE = re.compile(r"[a-zA-Z]+")
_SPOKEN_DIGITS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


@dataclass(frozen=True)
class ParsedToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


def _extract_phone_number(text: str) -> str | None:
    match = _PHONE_RE.search(text)
    if not match:
        spoken_digits = _extract_spoken_digits(text)
        if spoken_digits:
            return spoken_digits
        return None

    raw = match.group(1)
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("++"):
        digits = digits.lstrip("+")
        digits = f"+{digits}"
    return digits.strip() or None


def _extract_spoken_digits(text: str) -> str | None:
    tokens = _SPOKEN_DIGIT_RE.findall(text.lower())
    digits = [(_SPOKEN_DIGITS.get(token)) for token in tokens]
    digits = [digit for digit in digits if digit is not None]
    if len(digits) < 7:
        return None
    return "".join(digits)


def _extract_sip_phone_number(room: rtc.Room) -> str | None:
    for participant in room.remote_participants.values():
        if getattr(participant, "kind", None) != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            continue

        attrs = participant.attributes or {}
        phone = attrs.get("sip.phoneNumber")
        if isinstance(phone, str) and phone.strip():
            return phone.strip()

        identity = getattr(participant, "identity", "")
        if isinstance(identity, str) and identity.strip().startswith("+") and identity.strip()[1:].isdigit():
            return identity.strip()

    return None


def _handoff_tool_to_phase(tool_name: str) -> Phase | None:
    if tool_name == "handoff_to_CustomerIntake":
        return Phase.CUSTOMER_INTAKE
    if tool_name == "handoff_to_ServiceCollection":
        return Phase.SERVICE_COLLECTION
    if tool_name == "handoff_to_Booking":
        return Phase.BOOKING
    return None


def _fallback_parse_then_action(then_action: str) -> list[ParsedToolCall]:
    calls: list[ParsedToolCall] = []

    for match in re.finditer(r"\bCall\s+([A-Za-z_][A-Za-z0-9_]*)\b", then_action, flags=re.I):
        name = match.group(1)
        calls.append(ParsedToolCall(call_id=f"tool-{uuid.uuid4().hex}", name=name, arguments={}))

    for tool_name in ("handoff_to_CustomerIntake", "handoff_to_ServiceCollection", "handoff_to_Booking"):
        if tool_name in then_action and not any(c.name == tool_name for c in calls):
            calls.append(ParsedToolCall(call_id=f"tool-{uuid.uuid4().hex}", name=tool_name, arguments={}))

    return calls


class VapiAdapterAgent(Agent):
    def __init__(
        self,
        *,
        backend_client: BackendToolsClient,
        call_id_fallback: str = "local-session",
        sip_phone_number: str | None = None,
        tool_llm: google.LLM | None = None,
    ) -> None:
        super().__init__(
            instructions=(
                "You are a voice agent that follows backend tool instructions and only speaks when told."
            )
        )
        self._backend = backend_client
        self._call_id_fallback = call_id_fallback
        self._tool_llm = tool_llm

        self._flow = FlowController(sip_phone_number=sip_phone_number)
        self._sip_phone_number: str | None = sip_phone_number
        self._skip_preflight = os.getenv("SKIP_CALLBACK_PREFLIGHT", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        self._started = False
        self._entered_main_flow = False
        self._fatal_error = False
        self._then_action_fallback_spoken = False

        schemas = load_tool_schemas()
        self._tool_names: set[str] = {s.get("name", "") for s in schemas if isinstance(s.get("name"), str)}
        self._llm_tools = [
            function_tool(self._noop_tool, raw_schema={"name": s["name"], "description": s.get("description"), "parameters": s.get("parameters", {})})
            for s in schemas
            if isinstance(s, dict)
            and isinstance(s.get("name"), str)
            and s.get("name") != "get_case_status"
        ]

    async def _noop_tool(self, raw_arguments: dict[str, object], context: Any) -> None:
        return None

    @property
    def call_id(self) -> str:
        room = getattr(self.session, "room", None)
        room_name = getattr(room, "name", None)
        if isinstance(room_name, str) and room_name.strip():
            return room_name
        return self._call_id_fallback

    def _update_sip_phone_number_from_room(self) -> None:
        room = getattr(self.session, "room", None)
        if room is None:
            return

        extracted = _extract_sip_phone_number(room)
        if extracted and extracted != self._sip_phone_number:
            self._sip_phone_number = extracted
            self._flow.sip_phone_number = extracted
            logger.info("Detected SIP phone number: %s", extracted)

    async def on_enter(self) -> None:
        self._update_sip_phone_number_from_room()
        await self._maybe_start_preflight()

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: Any) -> None:
        if self._fatal_error:
            return

        self._update_sip_phone_number_from_room()

        user_text = getattr(new_message, "text_content", None) or ""
        user_text = user_text.strip()
        if not user_text:
            return

        if not self._started:
            await self._maybe_start_preflight()

        if not self._flow.can_call_get_case_status:
            await self._handle_preflight_turn(user_text)
            return

        if not self._entered_main_flow:
            self._entered_main_flow = True
            self.session.say("Thanks — how can I help today?")
            return

        await self._handle_business_turn(user_text)

    async def _maybe_start_preflight(self) -> None:
        if self._started:
            return

        self._started = True
        if self._skip_preflight and not self._sip_phone_number:
            self._flow.bypass_preflight(callback_number="web")
            return

        await self._run_actions(self._flow.start())

    async def _handle_preflight_turn(self, user_text: str) -> None:
        phone_in_text = _extract_phone_number(user_text)

        actions: list[Action] | None = None
        if self._flow.confirmed_callback_number is None and self._flow.sip_phone_number:
            if _AFFIRMATIVE_RE.search(user_text):
                actions = self._flow.on_user_callback_confirmation(confirmed=True)
            elif _NEGATIVE_RE.search(user_text):
                actions = self._flow.on_user_callback_confirmation(confirmed=False)
            elif phone_in_text:
                actions = self._flow.on_user_provided_callback_number(callback_number=phone_in_text)
            else:
                self.session.say("Please say yes or no — or tell me the best callback number.")
                return

        elif phone_in_text:
            actions = self._flow.on_user_provided_callback_number(callback_number=phone_in_text)
        else:
            self.session.say("What’s the best callback number for you?")
            return

        await self._run_actions(actions)

    async def _handle_business_turn(self, user_text: str) -> None:
        try:
            case_status = await self._call_backend_tool(
                tool_call_id=f"tool-{uuid.uuid4().hex}",
                tool_name="get_case_status",
                tool_arguments={"last_user_message": user_text},
            )
        except BackendToolsClientError:
            await self._speak_backend_unreachable_once()
            return

        self._flow.on_tool_result(tool_name="get_case_status", result=case_status)
        await self._run_actions(self._flow.plan_actions_from_case_status(case_status))

    async def _run_actions(self, actions: list[Action]) -> None:
        queue: list[Action] = list(actions)
        while queue and not self._fatal_error:
            action = queue.pop(0)
            if isinstance(action, SpeakAction):
                self.session.say(action.text)
                continue

            if not isinstance(action, ToolAction):
                continue

            if action.name == "__then_action__":
                then_action = action.arguments.get("then_action")
                if isinstance(then_action, str) and then_action.strip():
                    await self._execute_then_action(then_action)
                continue

            if action.name == "__apply_detected_corrections__":
                corrections = action.arguments.get("detected_corrections")
                await self._execute_detected_corrections(corrections)
                continue

            try:
                tool_result = await self._call_backend_tool(
                    tool_call_id=f"tool-{uuid.uuid4().hex}",
                    tool_name=action.name,
                    tool_arguments=action.arguments,
                )
            except BackendToolsClientError:
                await self._speak_backend_unreachable_once()
                return

            followups = self._flow.on_tool_result(tool_name=action.name, result=tool_result)
            queue = list(followups) + queue

    async def _execute_then_action(self, then_action: str) -> None:
        try:
            tool_calls = await self._tool_calls_from_instruction(then_action)
        except Exception as exc:
            # Reason: Tool LLM failures should not make the agent go silent.
            logger.warning("then_action parsing failed; falling back to prompt", exc_info=exc)
            tool_calls = []

        if not tool_calls:
            self._speak_then_action_fallback()
            return

        for tool_call in tool_calls:
            await self._execute_tool_call(tool_call)

    def _speak_then_action_fallback(self) -> None:
        if self._then_action_fallback_spoken:
            return

        # Reason: Avoid silent turns when tool parsing fails (e.g., LLM timeouts).
        self._then_action_fallback_spoken = True
        self.session.say(_THEN_ACTION_FALLBACK_PROMPT)

    async def _execute_detected_corrections(self, detected_corrections: object) -> None:
        instruction = (
            "Apply these corrections by calling the appropriate tool(s): "
            f"{json.dumps(detected_corrections, default=str)}"
        )
        tool_calls = await self._tool_calls_from_instruction(instruction)
        for tool_call in tool_calls:
            await self._execute_tool_call(tool_call)

    async def _tool_calls_from_instruction(self, instruction: str) -> list[ParsedToolCall]:
        if self._tool_llm is None:
            return _fallback_parse_then_action(instruction)

        fast_calls = _fallback_parse_then_action(instruction)
        if fast_calls:
            return fast_calls

        chat_ctx = ChatContext()
        chat_ctx.add_message(
            role="system",
            content=(
                "You will be given a backend instruction. Your job is to call the appropriate function tool(s) "
                "with correct JSON arguments. Do not output any natural language."
            ),
        )
        chat_ctx.add_message(
            role="user",
            content=(
                f"Instruction:\n{instruction}\n\n"
                f"Known context:\nphase={self._flow.phase.value}\n"
                f"confirmed_callback_number={self._flow.confirmed_callback_number}\n"
            ),
        )

        calls_by_id: dict[str, tuple[str, str]] = {}
        conn_options = APIConnectOptions(
            max_retry=_int_env("GOOGLE_LLM_MAX_RETRY") or 3,
            retry_interval=_float_env("GOOGLE_LLM_RETRY_INTERVAL_S") or 2.0,
            timeout=_float_env("GOOGLE_LLM_TIMEOUT_S") or 15.0,
        )
        try:
            stream = self._tool_llm.chat(
                chat_ctx=chat_ctx,
                tools=self._llm_tools,
                conn_options=conn_options,
                tool_choice="required",
                parallel_tool_calls=True,
            )
            async with stream:
                async for chunk in stream:
                    if not chunk.delta or not chunk.delta.tool_calls:
                        continue

                    for call in chunk.delta.tool_calls:
                        if call.call_id not in calls_by_id:
                            calls_by_id[call.call_id] = (call.name, call.arguments or "")
                            continue

                        existing_name, existing_args = calls_by_id[call.call_id]
                        merged_name = call.name or existing_name
                        merged_args = existing_args + (call.arguments or "")
                        calls_by_id[call.call_id] = (merged_name, merged_args)
        except Exception as exc:
            # Reason: Gemini timeouts are common; fall back to regex parsing.
            logger.warning(
                "tool LLM stream failed; falling back to regex parsing",
                extra={
                    "tool_llm_timeout_s": conn_options.timeout,
                    "tool_llm_max_retry": conn_options.max_retry,
                    "tool_llm_retry_interval_s": conn_options.retry_interval,
                },
                exc_info=exc,
            )
            return _fallback_parse_then_action(instruction)

        parsed_calls: list[ParsedToolCall] = []
        for call_id, (name, raw_args) in calls_by_id.items():
            if name not in self._tool_names:
                continue

            try:
                arguments = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                arguments = {}

            if not isinstance(arguments, dict):
                arguments = {}

            parsed_calls.append(ParsedToolCall(call_id=call_id, name=name, arguments=arguments))

        if not parsed_calls:
            return _fallback_parse_then_action(instruction)

        return parsed_calls

    async def _execute_tool_call(self, tool_call: ParsedToolCall) -> None:
        phase = _handoff_tool_to_phase(tool_call.name)
        if phase:
            self._flow.phase = phase
            return

        try:
            result = await self._call_backend_tool(
                tool_call_id=tool_call.call_id,
                tool_name=tool_call.name,
                tool_arguments=tool_call.arguments,
            )
        except BackendToolsClientError:
            await self._speak_backend_unreachable_once()
            return

        followups = self._flow.on_tool_result(tool_name=tool_call.name, result=result)
        await self._run_actions(followups)

    async def _call_backend_tool(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._backend.call_tool(
            call_id=self.call_id,
            sip_phone_number=self._sip_phone_number,
            confirmed_callback_number=self._flow.confirmed_callback_number,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )

    async def _speak_backend_unreachable_once(self) -> None:
        if self._fatal_error:
            return

        self._fatal_error = True
        self.session.say("I'm having trouble connecting — please call back.")


server = _build_server()

DEFAULT_BACKEND_TOOLS_URL = "https://call-agent-development.up.railway.app/vapi/tools"


async def _on_session_end(ctx: JobContext) -> None:
    """Publish a session report (optional).

    Reason: we want a programmatic artifact (session report JSON) without having
    to open the LiveKit Cloud UI.
    """

    reports_url = os.getenv("SESSION_REPORTS_URL", "").strip()
    if not reports_url:
        return

    token = os.getenv("SESSION_REPORTS_TOKEN", "").strip() or None
    publisher = SessionReportPublisher(reports_url=reports_url, token=token)
    await publisher.publish(ctx)


def _prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = _prewarm


@server.rtc_session(agent_name=os.getenv("LIVEKIT_AGENT_NAME", "").strip(), on_session_end=_on_session_end)
async def entrypoint(ctx: JobContext) -> None:
    load_dotenv()
    ctx.log_context_fields = {"room": ctx.room.name}

    backend_tools_url = os.getenv("BACKEND_TOOLS_URL", DEFAULT_BACKEND_TOOLS_URL)

    llm_model = os.getenv("GOOGLE_LLM_MODEL", "gemini-2.5-flash")
    tool_llm = google.LLM(model=llm_model) if os.getenv("GOOGLE_API_KEY") else None
    tool_llm_timeout_s = _float_env("GOOGLE_LLM_TIMEOUT_S") or 15.0
    tool_llm_max_retry = _int_env("GOOGLE_LLM_MAX_RETRY") or 3
    tool_llm_retry_interval_s = _float_env("GOOGLE_LLM_RETRY_INTERVAL_S") or 2.0

    stt_model = os.getenv("DEEPGRAM_STT_MODEL", "flux-general-en")
    eager_eot_threshold_raw = os.getenv("DEEPGRAM_EAGER_EOT_THRESHOLD", "0.4")
    try:
        eager_eot_threshold = float(eager_eot_threshold_raw)
    except ValueError:
        eager_eot_threshold = 0.4
        logger.warning(
            "Invalid DEEPGRAM_EAGER_EOT_THRESHOLD=%r (expected float); using default=%s",
            eager_eot_threshold_raw,
            eager_eot_threshold,
        )
    else:
        # Reason: Deepgram rejects values outside this range with a 400, which makes the agent go silent.
        if eager_eot_threshold < 0.3 or eager_eot_threshold > 0.9:
            logger.warning(
                "Invalid DEEPGRAM_EAGER_EOT_THRESHOLD=%s (expected 0.3-0.9); clamping",
                eager_eot_threshold,
            )
            eager_eot_threshold = min(max(eager_eot_threshold, 0.3), 0.9)
    tts_model = os.getenv("CARTESIA_TTS_MODEL", "sonic-3")
    tts_voice = os.getenv("CARTESIA_VOICE_ID", "794f9389-aac1-45b6-b726-9d9369183238")
    tts_speed_raw = os.getenv("CARTESIA_SPEED", "").strip()
    tts_speed: float | None = None
    if tts_speed_raw:
        try:
            tts_speed = float(tts_speed_raw)
        except ValueError:
            logger.warning("Invalid CARTESIA_SPEED=%r (expected float); ignoring", tts_speed_raw)

    text_pacing_raw = os.getenv("CARTESIA_TEXT_PACING", "").strip().lower()
    text_pacing = text_pacing_raw in {"1", "true", "yes", "y", "on"}

    logger.info(
            "starting agent session",
            extra={
                "backend_tools_url": backend_tools_url,
                "tool_llm_enabled": bool(tool_llm),
                "tool_llm_model": llm_model if tool_llm else None,
                "tool_llm_timeout_s": tool_llm_timeout_s if tool_llm else None,
                "tool_llm_max_retry": tool_llm_max_retry if tool_llm else None,
                "tool_llm_retry_interval_s": tool_llm_retry_interval_s if tool_llm else None,
                "stt_model": stt_model,
                "eager_eot_threshold": eager_eot_threshold,
                "tts_model": tts_model,
                "tts_voice": tts_voice,
            "tts_speed": tts_speed,
            "tts_text_pacing": text_pacing,
            "has_deepgram_api_key": bool(os.getenv("DEEPGRAM_API_KEY")),
            "has_cartesia_api_key": bool(os.getenv("CARTESIA_API_KEY")),
            "has_google_api_key": bool(os.getenv("GOOGLE_API_KEY")),
        },
    )

    session = AgentSession(
        # Use Deepgram's STT-based endpointing (closest parity with Vapi's current settings).
        turn_detection="stt",
        stt=deepgram.STTv2(model=stt_model, eager_eot_threshold=eager_eot_threshold),
        tts=cartesia.TTS(model=tts_model, voice=tts_voice, speed=tts_speed, text_pacing=text_pacing),
        vad=ctx.proc.userdata["vad"],
    )

    @session.on("error")
    def _on_session_error(ev: ErrorEvent) -> None:
        # Reason: LiveKit Cloud "AgentSession is closing..." logs can omit the underlying exception.
        # Log the full error details (including traceback when available) so we can debug via `lk agent logs`.
        error_obj = ev.error

        # Most LiveKit error models include the actual exception in `.error` (excluded from JSON).
        underlying_exc = getattr(error_obj, "error", None)
        exc_info = None
        if isinstance(underlying_exc, BaseException) and underlying_exc.__traceback__ is not None:
            # Reason: Some exceptions include request headers in their message (can leak API keys).
            redacted_exc = RuntimeError(_redact_secrets(str(underlying_exc)))
            exc_info = (type(redacted_exc), redacted_exc, underlying_exc.__traceback__)
        elif isinstance(error_obj, BaseException) and error_obj.__traceback__ is not None:
            redacted_exc = RuntimeError(_redact_secrets(str(error_obj)))
            exc_info = (type(redacted_exc), redacted_exc, error_obj.__traceback__)

        recoverable = getattr(error_obj, "recoverable", None)
        label = getattr(error_obj, "label", None)
        error_type = getattr(error_obj, "type", None)

        remote_error = None
        status = None
        headers = getattr(underlying_exc, "headers", None)
        if headers:
            remote_error = headers.get("dg-error") or headers.get("x-error")
        status = getattr(underlying_exc, "status", None)

        log_extra = {
            "room": ctx.room.name,
            "job_id": getattr(ctx, "job", None).id if getattr(ctx, "job", None) else None,
            "error_model_type": type(error_obj).__name__,
            "error_type": error_type,
            "error_label": label,
            "recoverable": recoverable,
            "source_type": type(ev.source).__name__,
            "status": status,
            "remote_error": remote_error,
        }

        logger.error("AgentSession error", extra=log_extra, exc_info=exc_info)

    @session.on("close")
    def _on_session_close(ev: CloseEvent) -> None:
        close_error = getattr(ev, "error", None)
        close_error_dump = None
        if close_error is not None and hasattr(close_error, "model_dump"):
            close_error_dump = close_error.model_dump(exclude_none=True)
        logger.info(
            "AgentSession closing",
            extra={
                "room": ctx.room.name,
                "job_id": getattr(ctx, "job", None).id if getattr(ctx, "job", None) else None,
                "reason": getattr(ev, "reason", None),
                "error": close_error_dump,
            },
        )

    agent = VapiAdapterAgent(
        backend_client=BackendToolsClient(tools_url=backend_tools_url),
        call_id_fallback=ctx.room.name,
        tool_llm=tool_llm,
    )

    try:
        await session.start(agent=agent, room=ctx.room)
    except Exception:
        # Reason: Ensure *any* uncaught exception is visible in LiveKit Cloud logs.
        logger.exception("Unhandled exception in agent entrypoint", extra={"room": ctx.room.name})
        raise


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    cli.run_app(server)
