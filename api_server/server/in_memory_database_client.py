from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from api_server.models.check_vin_models import CheckVinArgs
from api_server.models.database_records import (
    CustomerRecord,
    ServiceOrderRecord,
    UnitForServiceOrderRecord,
    UnitRecord,
)
from api_server.models.inbound_models import InboundArgs
from api_server.models.new_customer_models import NewCustomerArgs
from api_server.models.store_service_order_models import StoreServiceOrderArgs
from api_server.models.store_unit_models import StoreUnitArgs
from api_server.models.update_number_models import UpdateNumberRequest


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _normalize_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


class InMemoryDatabaseClient:
    """In-memory DatabaseClient implementation for local debugging.

    This is intentionally minimal and non-durable. It is useful for running the
    API server without a configured Postgres instance during development.
    """

    def __init__(self) -> None:
        self._customers: dict[str, CustomerRecord] = {}
        self._customers_by_phone: dict[str, str] = {}
        self._units: dict[str, UnitRecord] = {}
        self._unit_customer: dict[str, str] = {}
        self._unit_by_vin: dict[str, str] = {}
        self._unit_by_customer_unit_number: dict[tuple[str, str], str] = {}
        self._units_by_customer_nickname: dict[tuple[str, str], list[str]] = {}
        self._service_orders: dict[str, ServiceOrderRecord] = {}

    def find_customer_by_phone_number(self, inbound_args: InboundArgs) -> CustomerRecord | None:
        customer_id = self._customers_by_phone.get(inbound_args.phone_number)
        if not customer_id:
            return None
        return self._customers.get(customer_id)

    def find_customer_by_id(self, customer_id: str) -> CustomerRecord | None:
        return self._customers.get(customer_id)

    def find_unit_by_vin_number(self, check_vin_args: CheckVinArgs) -> UnitRecord | None:
        unit_id = self._unit_by_vin.get(check_vin_args.vin_number)
        if not unit_id:
            return None
        return self._units.get(unit_id)

    def find_unit_by_unit_number(self, customer_id: str, unit_number: str) -> UnitRecord | None:
        unit_id = self._unit_by_customer_unit_number.get((customer_id, unit_number))
        if not unit_id:
            return None
        return self._units.get(unit_id)

    def find_units_by_nickname(self, customer_id: str, unit_nickname: str) -> list[UnitRecord]:
        unit_ids = self._units_by_customer_nickname.get((customer_id, unit_nickname), [])
        return [unit for unit_id in unit_ids if (unit := self._units.get(unit_id)) is not None]

    def create_customer(self, new_customer_args: NewCustomerArgs) -> str:
        customer_id = _new_id("CUST")
        contact_name = f"{new_customer_args.first_name} {new_customer_args.last_name}".strip()
        record = CustomerRecord(
            customer_id=customer_id,
            customer_name=contact_name,
            phone_number=new_customer_args.phone_number,
            email=new_customer_args.email_address,
            company_name=new_customer_args.company_name,
        )
        self._customers[customer_id] = record
        if record.phone_number:
            self._customers_by_phone[record.phone_number] = customer_id
        return customer_id

    def find_customer_for_unit_creation(self, store_unit_args: StoreUnitArgs) -> str | None:
        return self._customers_by_phone.get(store_unit_args.phone_number)

    def create_unit(self, store_unit_args: StoreUnitArgs, customer_id: str) -> str:
        unit_id = _new_id("UNIT")
        vin_number = store_unit_args.vin_number
        unit_number = store_unit_args.unit_number or _new_id("FLEET")
        record = UnitRecord(
            unit_id=unit_id,
            vin_number=vin_number,
            unit_number=unit_number,
            unit_nickname=_normalize_optional_str(store_unit_args.unit_nickname),
        )
        self._units[unit_id] = record
        self._unit_customer[unit_id] = customer_id
        if vin_number:
            self._unit_by_vin[vin_number] = unit_id
        self._unit_by_customer_unit_number[(customer_id, unit_number)] = unit_id
        if record.unit_nickname:
            key = (customer_id, record.unit_nickname)
            self._units_by_customer_nickname.setdefault(key, []).append(unit_id)
        return unit_id

    def update_customer_phone_number(self, update_number_request: UpdateNumberRequest) -> str | None:
        first_name = update_number_request.body.args.first_name.strip()
        last_name = update_number_request.body.args.last_name.strip()
        target_name = " ".join(part for part in (first_name, last_name) if part)

        for customer_id, customer in self._customers.items():
            if customer.customer_name.strip().lower() != target_name.lower():
                continue
            return self.update_customer(customer_id, {"phone_number": update_number_request.new_phone_number})

        return None

    def update_customer(self, customer_id: str, updates: dict[str, object]) -> str | None:
        existing = self._customers.get(customer_id)
        if existing is None:
            return None

        contact_name = _normalize_optional_str(updates.get("contact_name"))
        email = _normalize_optional_str(updates.get("email")) or _normalize_optional_str(
            updates.get("email_address")
        )
        company_name = _normalize_optional_str(updates.get("company_name"))
        phone_number = _normalize_optional_str(updates.get("phone_number"))

        new_record = replace(
            existing,
            customer_name=contact_name if contact_name is not None else existing.customer_name,
            phone_number=phone_number if phone_number is not None else existing.phone_number,
            email=email if email is not None else existing.email,
            company_name=company_name if company_name is not None else existing.company_name,
        )

        if existing.phone_number and existing.phone_number != new_record.phone_number:
            self._customers_by_phone.pop(existing.phone_number, None)
        if new_record.phone_number:
            self._customers_by_phone[new_record.phone_number] = customer_id

        self._customers[customer_id] = new_record
        return customer_id

    def customer_exists(self, store_service_order_args: StoreServiceOrderArgs) -> bool:
        return store_service_order_args.customer_id in self._customers

    def find_service_order_by_id(self, order_id: str) -> ServiceOrderRecord | None:
        return self._service_orders.get(order_id)

    def find_unit_for_service_order(
        self, store_service_order_args: StoreServiceOrderArgs
    ) -> UnitForServiceOrderRecord | None:
        unit_id = store_service_order_args.unit_id
        customer_id = self._unit_customer.get(unit_id)
        if customer_id is None:
            return None
        return UnitForServiceOrderRecord(unit_id=unit_id, customer_id=customer_id)

    def update_service_order(self, order_id: str, updates: dict[str, object]) -> str | None:
        existing = self._service_orders.get(order_id)
        if existing is None:
            return None

        unit_id = _normalize_optional_str(updates.get("unit_id")) or existing.unit_id
        customer_id = existing.customer_id
        new_record = ServiceOrderRecord(
            service_order_id=existing.service_order_id,
            customer_id=customer_id,
            unit_id=unit_id,
        )
        self._service_orders[order_id] = new_record
        return order_id

    def create_service_order(self, store_service_order_args: StoreServiceOrderArgs) -> str:
        order_id = _new_id("SO")
        record = ServiceOrderRecord(
            service_order_id=order_id,
            customer_id=store_service_order_args.customer_id,
            unit_id=store_service_order_args.unit_id,
        )
        self._service_orders[order_id] = record
        return order_id

