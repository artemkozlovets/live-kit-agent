from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal


class Phase(str, Enum):
    CUSTOMER_INTAKE = "customer_intake"
    SERVICE_COLLECTION = "service_collection"
    BOOKING = "booking"


@dataclass(frozen=True)
class SpeakAction:
    type: Literal["speak"]
    text: str


@dataclass(frozen=True)
class ToolAction:
    type: Literal["tool"]
    name: str
    arguments: dict[str, Any]


Action = SpeakAction | ToolAction


class FlowController:
    MAX_PHONE_VALIDATION_ATTEMPTS = 3

    def __init__(self, *, sip_phone_number: str | None) -> None:
        self.phase: Phase = Phase.CUSTOMER_INTAKE
        self.sip_phone_number = sip_phone_number

        self.confirmed_callback_number: str | None = None
        self.normalized_callback_number: str | None = None

        self._phone_validation_attempts = 0
        self._customer_checked = False

    @property
    def can_call_get_case_status(self) -> bool:
        return self._customer_checked and self.normalized_callback_number is not None

    def start(self) -> list[Action]:
        if self.sip_phone_number:
            return [
                SpeakAction(
                    type="speak",
                    text=f"I have you as {self.sip_phone_number}. Is that the best callback number?",
                )
            ]
        return [
            SpeakAction(
                type="speak",
                text="What's the best callback number in case we get disconnected?",
            )
        ]

    def bypass_preflight(self, *, callback_number: str) -> None:
        self.confirmed_callback_number = callback_number
        self.normalized_callback_number = callback_number
        self._customer_checked = True

    def on_user_callback_confirmation(self, *, confirmed: bool) -> list[Action]:
        if confirmed:
            if not self.sip_phone_number:
                raise ValueError("No SIP phone number available to confirm")
            return self.on_user_provided_callback_number(callback_number=self.sip_phone_number)

        self.confirmed_callback_number = None
        self.normalized_callback_number = None
        return [
            SpeakAction(
                type="speak",
                text="Okay — what’s the best callback number for you?",
            )
        ]

    def on_user_provided_callback_number(self, *, callback_number: str) -> list[Action]:
        if not isinstance(callback_number, str) or not callback_number.strip():
            raise ValueError("callback_number is required")

        self.confirmed_callback_number = callback_number
        self.normalized_callback_number = None
        return [
            ToolAction(
                type="tool",
                name="validate_phone",
                arguments={"phone_number": callback_number},
            )
        ]

    def on_tool_result(self, *, tool_name: str, result: dict[str, Any]) -> list[Action]:
        if tool_name == "validate_phone":
            return self._on_validate_phone_result(result)
        if tool_name == "check_customer":
            return self._on_check_customer_result(result)
        if tool_name == "register_new_customer":
            self._customer_checked = True
            self._apply_phase_transitions(result)
            return []
        if tool_name == "get_case_status":
            self._apply_phase_transitions(result)
            return []
        return []

    def plan_actions_from_case_status(self, case_status: dict[str, Any]) -> list[Action]:
        response_mode = case_status.get("response_mode")
        immediate_message = case_status.get("immediate_message")
        then_action = case_status.get("then_action")
        detected_corrections = case_status.get("detected_corrections")

        actions: list[Action] = []
        if response_mode == "update_first":
            if detected_corrections:
                actions.append(
                    ToolAction(
                        type="tool",
                        name="__apply_detected_corrections__",
                        arguments={"detected_corrections": detected_corrections},
                    )
                )
            actions.append(SpeakAction(type="speak", text="Got it."))
            return actions

        if response_mode == "tool_first":
            if isinstance(then_action, str) and then_action.strip():
                actions.append(
                    ToolAction(
                        type="tool",
                        name="__then_action__",
                        arguments={"then_action": then_action},
                    )
                )
            if isinstance(immediate_message, str) and immediate_message.strip():
                actions.append(SpeakAction(type="speak", text=immediate_message))
            return actions

        if response_mode == "speak_first":
            if isinstance(immediate_message, str) and immediate_message.strip():
                actions.append(SpeakAction(type="speak", text=immediate_message))
            if isinstance(then_action, str) and then_action.strip():
                actions.append(
                    ToolAction(
                        type="tool",
                        name="__then_action__",
                        arguments={"then_action": then_action},
                    )
                )
            return actions

        if isinstance(immediate_message, str) and immediate_message.strip():
            actions.append(SpeakAction(type="speak", text=immediate_message))
        if isinstance(then_action, str) and then_action.strip():
            actions.append(
                ToolAction(type="tool", name="__then_action__", arguments={"then_action": then_action})
            )
        return actions

    def _on_validate_phone_result(self, result: dict[str, Any]) -> list[Action]:
        is_valid = result.get("valid")
        if is_valid is True:
            formatted = result.get("formatted")
            if isinstance(formatted, str) and formatted.strip():
                # After confirmation, normalize (E.164) and use the normalized value consistently.
                self.confirmed_callback_number = formatted
                self.normalized_callback_number = formatted
            elif self.confirmed_callback_number:
                self.normalized_callback_number = self.confirmed_callback_number
            return [
                ToolAction(
                    type="tool",
                    name="check_customer",
                    arguments={"phone_number": self.normalized_callback_number},
                )
            ]

        self._phone_validation_attempts += 1
        attempt = result.get("attempt")
        max_attempts = result.get("max_attempts")
        proceed_unvalidated = result.get("proceed_unvalidated") is True

        if isinstance(attempt, int) and attempt > self._phone_validation_attempts:
            self._phone_validation_attempts = attempt

        max_attempts_int = (
            max_attempts
            if isinstance(max_attempts, int) and max_attempts > 0
            else self.MAX_PHONE_VALIDATION_ATTEMPTS
        )

        if proceed_unvalidated or self._phone_validation_attempts >= max_attempts_int:
            self.normalized_callback_number = self.confirmed_callback_number
            return [
                ToolAction(
                    type="tool",
                    name="check_customer",
                    arguments={"phone_number": self.normalized_callback_number},
                )
            ]

        return [
            SpeakAction(
                type="speak",
                text="That number didn’t look valid. What’s the best callback number for you?",
            )
        ]

    def _on_check_customer_result(self, result: dict[str, Any]) -> list[Action]:
        self._customer_checked = True
        self._apply_phase_transitions(result)
        return []

    def _apply_phase_transitions(self, result: dict[str, Any]) -> None:
        next_action = result.get("next_action")
        if isinstance(next_action, str):
            self._apply_handoff_from_text(next_action)

        ready_for_handoff = result.get("ready_for_handoff")
        if isinstance(ready_for_handoff, dict):
            if ready_for_handoff.get("to_booking") is True:
                self.phase = Phase.BOOKING
            elif ready_for_handoff.get("to_service_collection") is True:
                self.phase = Phase.SERVICE_COLLECTION

    def _apply_handoff_from_text(self, text: str) -> None:
        if "handoff_to_Booking" in text:
            self.phase = Phase.BOOKING
        elif "handoff_to_ServiceCollection" in text:
            self.phase = Phase.SERVICE_COLLECTION
        elif "handoff_to_CustomerIntake" in text:
            self.phase = Phase.CUSTOMER_INTAKE
