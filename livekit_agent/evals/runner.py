from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Sequence


@dataclass(frozen=True)
class ToolCallTrace:
    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    call_id: str
    customer_number: str | None
    sip_number: str | None


@dataclass(frozen=True)
class TraceEvent:
    kind: Literal["tool", "say"]
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


BackendResult = dict[str, Any]
BackendResultFactory = Callable[[ToolCallTrace], BackendResult]


@dataclass(frozen=True)
class BackendStep:
    name: str
    result: BackendResult | BackendResultFactory | Exception
    assert_trace: Callable[[ToolCallTrace], None] | None = None


@dataclass(frozen=True)
class EvalScenario:
    name: str
    description: str
    user_turns: Sequence[str]
    backend_steps: Sequence[BackendStep]
    sip_phone_number: str | None = None
    tool_llm: object | None = None
    assert_trace: Callable[["EvalTrace"], None] | None = None


@dataclass(frozen=True)
class EvalTrace:
    scenario: EvalScenario
    assistant_messages: list[str]
    tool_calls: list[ToolCallTrace]
    events: list[TraceEvent]


@dataclass(frozen=True)
class EvalResult:
    scenario: EvalScenario
    ok: bool
    error: str | None = None
    trace: EvalTrace | None = None


def _extract_tool_call(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any], str | None, str | None]:
    call = payload.get("call") if isinstance(payload, dict) else None
    if not isinstance(call, dict):
        raise ValueError("Invalid tools v2 payload: missing call object")

    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("Invalid tools v2 payload: call.id missing")

    tool_calls = payload.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        raise ValueError("Invalid tools v2 payload: missing tool_calls")

    tool_call = tool_calls[0]
    if not isinstance(tool_call, dict):
        raise ValueError("Invalid tools v2 payload: tool_calls[0] must be an object")

    tool_call_id = tool_call.get("id")
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("arguments")

    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
        raise ValueError("Invalid tools v2 payload: tool_calls[0].id missing")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("Invalid tools v2 payload: tool_calls[0].name missing")
    if not isinstance(tool_args, dict):
        raise ValueError("Invalid tools v2 payload: tool_calls[0].arguments must be an object")

    customer_number: str | None = None
    call_customer = call.get("customer")
    if isinstance(call_customer, dict) and isinstance(call_customer.get("number"), str):
        customer_number = call_customer.get("number")

    sip_number: str | None = None
    customer = payload.get("customer")
    if isinstance(customer, dict) and isinstance(customer.get("number"), str):
        sip_number = customer.get("number")

    return tool_call_id, tool_name, tool_args, customer_number, sip_number


async def run_eval_scenario(scenario: EvalScenario, *, timeout_s: float = 2.0) -> EvalResult:
    # Ensure LiveKit Agents can safely import in restricted environments.
    os.environ.setdefault("NUM_CPUS", "2")

    assistant_messages: list[str] = []
    tool_calls: list[ToolCallTrace] = []
    events: list[TraceEvent] = []

    steps = list(scenario.backend_steps)

    async def post_json(_: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        nonlocal steps

        tool_call_id, tool_name, tool_args, customer_number, sip_number = _extract_tool_call(payload)
        trace = ToolCallTrace(
            tool_call_id=tool_call_id,
            name=tool_name,
            arguments=tool_args,
            call_id=str(payload["call"]["id"]),
            customer_number=customer_number,
            sip_number=sip_number,
        )
        tool_calls.append(trace)
        events.append(TraceEvent(kind="tool", name=tool_name, payload={"arguments": tool_args}))

        if not steps:
            raise AssertionError(f"Unexpected tool call: {tool_name}")

        step = steps.pop(0)
        if step.name != tool_name:
            raise AssertionError(f"Expected tool {step.name}, got {tool_name}")

        if step.assert_trace is not None:
            step.assert_trace(trace)

        if isinstance(step.result, Exception):
            raise step.result

        result_obj = step.result(trace) if callable(step.result) else step.result
        return {"results": [{"tool_call_id": tool_call_id, "name": tool_name, "ok": True, "result": result_obj}]}

    # Import lazily so NUM_CPUS is set first.
    from livekit.agents import AgentSession, ChatContext  # noqa: WPS433

    from livekit_agent.agent import VapiAdapterAgent  # noqa: WPS433
    from livekit_agent.backend_tools_client import BackendToolsClient  # noqa: WPS433

    backend = BackendToolsClient(tools_url="https://example.test/tools", post_json=post_json, tools_token="test-secret")
    agent = VapiAdapterAgent(
        backend_client=backend,
        call_id_fallback="eval-room",
        sip_phone_number=scenario.sip_phone_number,
        tool_llm=scenario.tool_llm,  # type: ignore[arg-type]
    )

    class _Msg:
        def __init__(self, text: str) -> None:
            self.text_content = text

    try:
        async with AgentSession() as session:
            @session.on("conversation_item_added")
            def on_item(ev: Any) -> None:
                item = getattr(ev, "item", None)
                if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant":
                    assistant_messages.append((getattr(item, "text_content", None) or "").strip())

            await asyncio.wait_for(session.start(agent), timeout=timeout_s)

            # Patch say() so event ordering is deterministic for response_mode evals.
            orig_say = session.say

            def _say(text: str) -> None:
                events.append(TraceEvent(kind="say", name=text))
                orig_say(text)

            session.say = _say  # type: ignore[assignment]

            # Let the initial prompt land.
            await asyncio.sleep(0.05)

            for turn in scenario.user_turns:
                await asyncio.wait_for(agent.on_user_turn_completed(ChatContext(), _Msg(turn)), timeout=timeout_s)
                await asyncio.sleep(0.05)

        trace = EvalTrace(
            scenario=scenario,
            assistant_messages=assistant_messages,
            tool_calls=tool_calls,
            events=events,
        )
        if steps:
            missing = ", ".join(step.name for step in steps[:5])
            raise AssertionError(f"Backend steps not consumed (next up: {missing})")

        if scenario.assert_trace is not None:
            scenario.assert_trace(trace)

        return EvalResult(scenario=scenario, ok=True, trace=trace)
    except Exception as exc:
        trace = EvalTrace(
            scenario=scenario,
            assistant_messages=assistant_messages,
            tool_calls=tool_calls,
            events=events,
        )
        return EvalResult(scenario=scenario, ok=False, error=f"{type(exc).__name__}: {exc}", trace=trace)


async def run_eval_suite(
    scenarios: Sequence[EvalScenario],
    *,
    timeout_s: float = 2.0,
) -> list[EvalResult]:
    results: list[EvalResult] = []
    for scenario in scenarios:
        results.append(await run_eval_scenario(scenario, timeout_s=timeout_s))
    return results


def format_results(results: Sequence[EvalResult]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    failed = total - passed

    lines: list[str] = [f"evals: {passed}/{total} passed"]
    if failed:
        for res in results:
            if res.ok:
                continue
            lines.append(f"- FAIL {res.scenario.name}: {res.error}")
    return "\n".join(lines)


def exit_code(results: Sequence[EvalResult]) -> int:
    return 0 if all(r.ok for r in results) else 1


def _maybe_enable_debug_tracebacks() -> None:
    if os.getenv("EVALS_DEBUG_TRACEBACKS") == "1":
        return
    sys.tracebacklimit = 0
