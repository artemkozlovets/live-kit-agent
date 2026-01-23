from livekit_agent.flow_controller import FlowController, Phase, SpeakAction, ToolAction


def test_no_get_case_status_call_before_callback_number_confirmed() -> None:
    controller = FlowController(sip_phone_number="+15551230000")

    start_actions = controller.start()
    assert len(start_actions) == 1
    assert isinstance(start_actions[0], SpeakAction)
    assert controller.can_call_get_case_status is False

    actions = controller.on_user_callback_confirmation(confirmed=True)
    assert actions == [
        ToolAction(type="tool", name="validate_phone", arguments={"phone_number": "+15551230000"})
    ]
    assert controller.can_call_get_case_status is False

    actions = controller.on_tool_result(
        tool_name="validate_phone",
        result={"valid": True, "formatted": "+15551230000"},
    )
    assert actions == [
        ToolAction(type="tool", name="check_customer", arguments={"phone_number": "+15551230000"})
    ]
    assert controller.can_call_get_case_status is False

    controller.on_tool_result(
        tool_name="check_customer",
        result={"found": True, "next_action": "Proceed. Call handoff_to_ServiceCollection."},
    )
    assert controller.can_call_get_case_status is True


def test_caller_rejects_sip_number_collects_new_callback_number() -> None:
    controller = FlowController(sip_phone_number="+15551230000")

    actions = controller.on_user_callback_confirmation(confirmed=False)
    assert actions and isinstance(actions[0], SpeakAction)
    assert controller.confirmed_callback_number is None

    actions = controller.on_user_provided_callback_number(callback_number="+15559990000")
    assert actions == [
        ToolAction(type="tool", name="validate_phone", arguments={"phone_number": "+15559990000"})
    ]

    actions = controller.on_tool_result(
        tool_name="validate_phone",
        result={"valid": True, "formatted": "+15559990000"},
    )
    assert actions == [
        ToolAction(type="tool", name="check_customer", arguments={"phone_number": "+15559990000"})
    ]


def test_invalid_phone_number_path_is_bounded_and_proceeds_unvalidated() -> None:
    controller = FlowController(sip_phone_number=None)

    start_actions = controller.start()
    assert start_actions and isinstance(start_actions[0], SpeakAction)
    assert controller.can_call_get_case_status is False

    controller.on_user_provided_callback_number(callback_number="123")
    actions = controller.on_tool_result(
        tool_name="validate_phone",
        result={"valid": False, "attempt": 1, "max_attempts": 3},
    )
    assert actions and isinstance(actions[0], SpeakAction)

    controller.on_user_provided_callback_number(callback_number="123")
    controller.on_tool_result(
        tool_name="validate_phone",
        result={"valid": False, "attempt": 2, "max_attempts": 3},
    )

    controller.on_user_provided_callback_number(callback_number="123")
    actions = controller.on_tool_result(
        tool_name="validate_phone",
        result={"valid": False, "attempt": 3, "max_attempts": 3, "proceed_unvalidated": True},
    )
    assert actions == [
        ToolAction(type="tool", name="check_customer", arguments={"phone_number": "123"})
    ]


def test_phase_transitions_from_next_action_handoff_text() -> None:
    controller = FlowController(sip_phone_number=None)
    assert controller.phase == Phase.CUSTOMER_INTAKE

    controller.on_tool_result(tool_name="check_customer", result={"next_action": "Call handoff_to_ServiceCollection."})
    assert controller.phase == Phase.SERVICE_COLLECTION

    controller.on_tool_result(tool_name="get_case_status", result={"next_action": "Call handoff_to_Booking."})
    assert controller.phase == Phase.BOOKING


def test_phase_transitions_from_ready_for_handoff_flags() -> None:
    controller = FlowController(sip_phone_number=None)
    controller.phase = Phase.CUSTOMER_INTAKE

    controller.on_tool_result(
        tool_name="get_case_status",
        result={"ready_for_handoff": {"to_service_collection": True, "to_booking": False}},
    )
    assert controller.phase == Phase.SERVICE_COLLECTION

    controller.on_tool_result(
        tool_name="get_case_status",
        result={"ready_for_handoff": {"to_service_collection": True, "to_booking": True}},
    )
    assert controller.phase == Phase.BOOKING


def test_response_mode_ordering_speak_first_vs_tool_first_vs_update_first() -> None:
    controller = FlowController(sip_phone_number=None)

    actions = controller.plan_actions_from_case_status(
        {
            "response_mode": "speak_first",
            "immediate_message": "Hi there.",
            "then_action": "Call add_service.",
        }
    )
    assert [a.type for a in actions] == ["speak", "tool"]

    actions = controller.plan_actions_from_case_status(
        {
            "response_mode": "tool_first",
            "immediate_message": "Done.",
            "then_action": "Call add_service.",
        }
    )
    assert [a.type for a in actions] == ["tool", "speak"]

    actions = controller.plan_actions_from_case_status(
        {
            "response_mode": "update_first",
            "detected_corrections": {"field": "email_address", "customer_id": "cust-1"},
            "then_action": "Call update_customer.",
        }
    )
    assert [a.type for a in actions] == ["tool", "speak"]
    assert isinstance(actions[1], SpeakAction)
    assert actions[1].text == "Got it."

