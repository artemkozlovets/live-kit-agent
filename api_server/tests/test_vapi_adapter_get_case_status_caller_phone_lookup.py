"""get_case_status: lookup by caller phone number from payload."""

import os

from fastapi.testclient import TestClient

from api_server.models.database_records import CustomerRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(
        self,
        *,
        customers_by_phone: dict[str, CustomerRecord] | None = None,
        customers_by_id: dict[str, CustomerRecord] | None = None,
        should_raise: bool = False,
    ) -> None:
        self.customers_by_phone = customers_by_phone or {}
        self.customers_by_id = customers_by_id or {}
        self.should_raise = should_raise

    def find_customer_by_phone_number(self, inbound_args):  # noqa: ANN001
        if self.should_raise:
            raise RuntimeError("DB unavailable")
        return self.customers_by_phone.get(inbound_args.phone_number)

    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return self.customers_by_id.get(customer_id)


def _post_get_case_status(*, test_client: TestClient, call_id: str, payload_call: dict, tool_args: dict) -> dict:
    token = "test-secret"
    previous_token = os.environ.get("TOOLS_TOKEN")
    os.environ["TOOLS_TOKEN"] = token
    payload = {
        "call": {"id": call_id, **payload_call},
        "tool_calls": [
            {
                "id": "tool-call-get-case-status-caller",
                "name": "get_case_status",
                "arguments": tool_args,
            }
        ],
    }
    try:
        response = test_client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": token})
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["results"][0]["ok"] is True
        return response_data["results"][0]["result"]
    finally:
        if previous_token is None:
            os.environ.pop("TOOLS_TOKEN", None)
        else:
            os.environ["TOOLS_TOKEN"] = previous_token


def test_get_case_status_prefills_customer_from_caller_phone() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-caller-phone"
    session_store.clear(call_id)

    customer_record = CustomerRecord(
        customer_id="CUST-200",
        customer_name="John Johnson",
        phone_number="+15551230000",
        company_name="Acme Logistics",
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(
        customers_by_phone={"+15551230000": customer_record}
    )
    try:
        test_client = TestClient(app)

        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            payload_call={"customer": {"number": "+15551230000"}},
            tool_args={"call_id": call_id, "last_user_message": "Hi"},
        )

        assert parsed_result["customer"] == {
            "id": "CUST-200",
            "first_name": "John",
            "last_name": "Johnson",
            "phone": "+15551230000",
            "email": None,
            "company": "Acme Logistics",
        }
        assert parsed_result["current_phase"] == "customer_intake"
        assert parsed_result["ready_for_handoff"] == {
            "to_service_collection": False,
            "to_booking": False,
        }
        assert parsed_result["response_mode"] == "speak_first"
        assert "John" in parsed_result["immediate_message"]
        assert "+15551230000" in parsed_result["immediate_message"]
        assert parsed_result["then_action"] == "Ask the caller to confirm the phone number."
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_confirmation_clears_phone_pending_flag() -> None:
    # Edge case: confirmation flips handoff readiness.
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-caller-confirmed"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-201",
            "customer_registered": True,
            "phone_confirmation_pending": True,
        },
    )

    customer_record = CustomerRecord(
        customer_id="CUST-201",
        customer_name="Maria Gomez",
        phone_number="+15551239999",
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(
        customers_by_id={"CUST-201": customer_record}
    )
    try:
        test_client = TestClient(app)

        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            payload_call={"customer": {"number": "+15551239999"}},
            tool_args={"call_id": call_id, "last_user_message": "Yes"},
        )

        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["ready_for_handoff"]["to_service_collection"] is True
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_phone_lookup_failure_falls_back_to_intake() -> None:
    # Failure case: DB lookup error should not break tool.
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-caller-db-fail"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(should_raise=True)
    try:
        test_client = TestClient(app)

        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            payload_call={"customer": {"number": "+15551230000"}},
            tool_args={"call_id": call_id},
        )

        assert parsed_result["customer"]["id"] is None
        assert parsed_result["current_phase"] == "customer_intake"
        assert parsed_result["missing_fields"] == ["first_name", "last_name", "phone"]
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_handoff_initiated_skips_confirmation() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-handoff-initiated"
    session_store.clear(call_id)

    customer_record = CustomerRecord(
        customer_id="CUST-300",
        customer_name="Jamie Rivera",
        phone_number="+15551236666",
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(
        customers_by_phone={"+15551236666": customer_record}
    )
    try:
        test_client = TestClient(app)

        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            payload_call={"customer": {"number": "+15551236666"}},
            tool_args={"call_id": call_id, "last_user_message": "Handoff initiated."},
        )

        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["ready_for_handoff"]["to_service_collection"] is True
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "What can I help you with today?"
        assert parsed_result["then_action"] == "Collect vehicle info and service complaint."
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_phone_confirmation_returns_service_prompt() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-phone-confirmation-prompt"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-201",
            "customer_registered": True,
            "phone_confirmation_pending": True,
        },
    )

    customer_record = CustomerRecord(
        customer_id="CUST-201",
        customer_name="Maria Gomez",
        phone_number="+15551239999",
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(
        customers_by_id={"CUST-201": customer_record}
    )
    try:
        test_client = TestClient(app)

        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            payload_call={"customer": {"number": "+15551239999"}},
            tool_args={"call_id": call_id, "last_user_message": "Yes"},
        )

        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "Great! What can I help you with?"
        assert parsed_result["then_action"] == "Collect service details."
    finally:
        app.dependency_overrides.pop(get_database_client, None)
