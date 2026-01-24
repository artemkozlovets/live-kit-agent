from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from livekit_agent.evals.fake_tool_llm import FakeChunk, FakeDelta, FakeToolCall, FakeToolLLM
from livekit_agent.evals.runner import BackendStep, EvalScenario, EvalTrace, TraceEvent


def _assert_in_order(haystack: list[str], needles: list[str]) -> None:
    idx = 0
    for needle in needles:
        while idx < len(haystack) and needle not in haystack[idx]:
            idx += 1
        if idx >= len(haystack):
            raise AssertionError(f"Expected to find '{needle}' after index {idx}")
        idx += 1


def _assert_event_order(events: list[TraceEvent], expected: list[str]) -> None:
    got = [f"{e.kind}:{e.name}" for e in events]
    start = 0
    for exp in expected:
        try:
            start = got.index(exp, start) + 1
        except ValueError as exc:
            raise AssertionError(f"Missing event '{exp}'. Got: {got}") from exc


def scenario_preflight_no_sip_speak_first_then_action() -> EvalScenario:
    def assert_validate_phone(trace) -> None:
        assert trace.customer_number == "5551234567"

    def assert_check_customer(trace) -> None:
        assert trace.customer_number == "+15551234567"
        assert trace.arguments.get("phone_number") == "+15551234567"

    def assert_trace(eval_trace: EvalTrace) -> None:
        _assert_in_order(
            eval_trace.assistant_messages,
            [
                "What's the best callback number",
                "Thanks — how can I help today?",
                "VIN",
            ],
        )
        assert [c.name for c in eval_trace.tool_calls] == [
            "validate_phone",
            "check_customer",
            "get_case_status",
            "get_session_summary",
        ]

    return EvalScenario(
        name="preflight_no_sip_speak_first",
        description="No SIP number; validate + check customer; speak_first ordering; then_action tool call.",
        user_turns=["5551234567", "Hi", "I need roadside assistance"],
        backend_steps=[
            BackendStep(
                name="validate_phone",
                result={"valid": True, "formatted": "+15551234567"},
                assert_trace=assert_validate_phone,
            ),
            BackendStep(
                name="check_customer",
                result={"found": True, "next_action": "Proceed. Call handoff_to_ServiceCollection."},
                assert_trace=assert_check_customer,
            ),
            BackendStep(
                name="get_case_status",
                result={
                    "response_mode": "speak_first",
                    "immediate_message": "Okay — what's the VIN or unit number?",
                    "then_action": "Call get_session_summary.",
                },
            ),
            BackendStep(name="get_session_summary", result={"ok": True}),
        ],
        assert_trace=assert_trace,
    )


def scenario_preflight_sip_yes() -> EvalScenario:
    def assert_trace(eval_trace: EvalTrace) -> None:
        _assert_in_order(
            eval_trace.assistant_messages,
            [
                "I have you as +15551230000",
                "Thanks — how can I help today?",
            ],
        )
        assert [c.name for c in eval_trace.tool_calls] == [
            "validate_phone",
            "check_customer",
            "get_case_status",
        ]

    return EvalScenario(
        name="preflight_sip_yes",
        description="SIP number present; user confirms yes; preflight completes.",
        sip_phone_number="+15551230000",
        user_turns=["yes", "Hi", "Help"],
        backend_steps=[
            BackendStep(name="validate_phone", result={"valid": True, "formatted": "+15551230000"}),
            BackendStep(name="check_customer", result={"found": True}),
            BackendStep(name="get_case_status", result={"immediate_message": "Okay.", "then_action": ""}),
        ],
        assert_trace=assert_trace,
    )


def scenario_preflight_sip_no_then_number() -> EvalScenario:
    def assert_trace(eval_trace: EvalTrace) -> None:
        _assert_in_order(
            eval_trace.assistant_messages,
            [
                "I have you as +15551230000",
                "Okay — what’s the best callback number",
                "Thanks — how can I help today?",
            ],
        )
        assert [c.name for c in eval_trace.tool_calls] == [
            "validate_phone",
            "check_customer",
        ]

    return EvalScenario(
        name="preflight_sip_no_then_number",
        description="SIP number present; user says no then provides number; preflight completes.",
        sip_phone_number="+15551230000",
        user_turns=["no", "5551234567", "Hi"],
        backend_steps=[
            BackendStep(name="validate_phone", result={"valid": True, "formatted": "+15551234567"}),
            BackendStep(name="check_customer", result={"found": True}),
        ],
        assert_trace=assert_trace,
    )


def scenario_invalid_phone_retries_then_proceeds() -> EvalScenario:
    def assert_trace(eval_trace: EvalTrace) -> None:
        assert [c.name for c in eval_trace.tool_calls] == [
            "validate_phone",
            "validate_phone",
            "validate_phone",
            "check_customer",
        ]
        assert any("didn’t look valid" in msg for msg in eval_trace.assistant_messages)

    return EvalScenario(
        name="invalid_phone_retries",
        description="Invalid phone number path; bounded retries; proceeds to check_customer unvalidated.",
        user_turns=["1234567890", "1234567890", "1234567890"],
        backend_steps=[
            BackendStep(name="validate_phone", result={"valid": False, "attempt": 1, "max_attempts": 3}),
            BackendStep(name="validate_phone", result={"valid": False, "attempt": 2, "max_attempts": 3}),
            BackendStep(
                name="validate_phone",
                result={"valid": False, "attempt": 3, "max_attempts": 3, "proceed_unvalidated": True},
            ),
            BackendStep(name="check_customer", result={"found": True}),
        ],
        assert_trace=assert_trace,
    )


def scenario_tool_first_ordering() -> EvalScenario:
    def assert_trace(eval_trace: EvalTrace) -> None:
        _assert_event_order(
            eval_trace.events,
            [
                "tool:add_service",
                "say:Added.",
            ],
        )

    return EvalScenario(
        name="tool_first_ordering",
        description="response_mode=tool_first runs tools before speaking immediate_message.",
        user_turns=["5551234567", "Hi", "Add towing"],
        backend_steps=[
            BackendStep(name="validate_phone", result={"valid": True, "formatted": "+15551234567"}),
            BackendStep(name="check_customer", result={"found": True}),
            BackendStep(
                name="get_case_status",
                result={"response_mode": "tool_first", "then_action": "Call add_service.", "immediate_message": "Added."},
            ),
            BackendStep(name="add_service", result={"ok": True}),
        ],
        assert_trace=assert_trace,
    )


def scenario_update_first_detected_corrections_via_tool_llm() -> EvalScenario:
    tool_llm = FakeToolLLM(
        responses=[
            [
                FakeChunk(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeToolCall(
                                call_id="call-1",
                                name="update_customer",
                                arguments='{"customer_id":"cust-1","email_address":"a@example.com"}',
                            )
                        ]
                    )
                )
            ]
        ]
    )

    def assert_trace(eval_trace: EvalTrace) -> None:
        _assert_event_order(
            eval_trace.events,
            [
                "tool:update_customer",
                "say:Got it.",
            ],
        )

    return EvalScenario(
        name="update_first_detected_corrections",
        description="response_mode=update_first applies detected_corrections via tool_llm before speaking.",
        tool_llm=tool_llm,
        user_turns=["5551234567", "Hi", "My email is wrong"],
        backend_steps=[
            BackendStep(name="validate_phone", result={"valid": True, "formatted": "+15551234567"}),
            BackendStep(name="check_customer", result={"found": True}),
            BackendStep(
                name="get_case_status",
                result={
                    "response_mode": "update_first",
                    "detected_corrections": {"customer_id": "cust-1", "email_address": "a@example.com"},
                },
            ),
            BackendStep(name="update_customer", result={"ok": True}),
        ],
        assert_trace=assert_trace,
    )


def scenario_llm_stream_merges_arguments() -> EvalScenario:
    tool_llm = FakeToolLLM(
        responses=[
            [
                FakeChunk(delta=FakeDelta(tool_calls=[FakeToolCall(call_id="c1", name="update_customer", arguments='{"customer_id":"cust-1",')])),
                FakeChunk(delta=FakeDelta(tool_calls=[FakeToolCall(call_id="c1", name="", arguments='"email_address":"x@y.com"}')])),
            ]
        ]
    )

    def assert_update_customer(trace) -> None:
        assert trace.arguments == {"customer_id": "cust-1", "email_address": "x@y.com"}

    def assert_trace(eval_trace: EvalTrace) -> None:
        assert [c.name for c in eval_trace.tool_calls] == [
            "validate_phone",
            "check_customer",
            "get_case_status",
            "update_customer",
        ]

    return EvalScenario(
        name="llm_stream_merges_args",
        description="tool_llm streaming merges partial JSON arguments across chunks.",
        tool_llm=tool_llm,
        user_turns=["5551234567", "Hi", "Update my email"],
        backend_steps=[
            BackendStep(name="validate_phone", result={"valid": True, "formatted": "+15551234567"}),
            BackendStep(name="check_customer", result={"found": True}),
            BackendStep(name="get_case_status", result={"then_action": "Update customer email."}),
            BackendStep(name="update_customer", result={"ok": True}, assert_trace=assert_update_customer),
        ],
        assert_trace=assert_trace,
    )


def scenario_llm_invalid_tool_name_falls_back_to_parser() -> EvalScenario:
    tool_llm = FakeToolLLM(
        responses=[
            [
                FakeChunk(delta=FakeDelta(tool_calls=[FakeToolCall(call_id="bad1", name="not_a_real_tool", arguments="{}")])),
            ]
        ]
    )

    def assert_trace(eval_trace: EvalTrace) -> None:
        assert [c.name for c in eval_trace.tool_calls] == [
            "validate_phone",
            "check_customer",
            "get_case_status",
            "add_service",
        ]

    return EvalScenario(
        name="llm_invalid_tool_fallback",
        description="If tool_llm returns unknown tool names, agent falls back to regex then_action parser.",
        tool_llm=tool_llm,
        user_turns=["5551234567", "Hi", "Add towing"],
        backend_steps=[
            BackendStep(name="validate_phone", result={"valid": True, "formatted": "+15551234567"}),
            BackendStep(name="check_customer", result={"found": True}),
            BackendStep(name="get_case_status", result={"response_mode": "tool_first", "then_action": "Call add_service.", "immediate_message": ""}),
            BackendStep(name="add_service", result={"ok": True}),
        ],
        assert_trace=assert_trace,
    )


def scenario_backend_unreachable_speaks_once() -> EvalScenario:
    def assert_trace(eval_trace: EvalTrace) -> None:
        assert any("trouble connecting" in msg for msg in eval_trace.assistant_messages)
        # Only one "trouble connecting" line even if the user keeps talking.
        assert sum("trouble connecting" in msg for msg in eval_trace.assistant_messages) == 1

    return EvalScenario(
        name="backend_unreachable_speaks_once",
        description="Backend exception triggers the fatal one-time error prompt and halts future turns.",
        user_turns=["5551234567", "hello", "are you there"],
        backend_steps=[
            BackendStep(name="validate_phone", result=RuntimeError("network down")),
        ],
        assert_trace=assert_trace,
    )


def all_scenarios() -> list[EvalScenario]:
    return [
        scenario_preflight_no_sip_speak_first_then_action(),
        scenario_preflight_sip_yes(),
        scenario_preflight_sip_no_then_number(),
        scenario_invalid_phone_retries_then_proceeds(),
        scenario_tool_first_ordering(),
        scenario_update_first_detected_corrections_via_tool_llm(),
        scenario_llm_stream_merges_arguments(),
        scenario_llm_invalid_tool_name_falls_back_to_parser(),
        scenario_backend_unreachable_speaks_once(),
    ]
