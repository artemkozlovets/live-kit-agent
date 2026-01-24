from pydantic import BaseModel


class StoreUnitArgs(BaseModel):
    first_name: str
    last_name: str
    company_name: str
    phone_number: str
    email_address: str | None = None
    vin_number: str
    unit_number: str | None = None
    unit_nickname: str | None = None
    license_plate_number: str | None = None
    license_plate_state: str | None = None
    chassis_type: str | None = None
    unit_subtype: str | None = None
    # --- Vehicle details (used for auto-creation with placeholders) ---
    make: str | None = None
    model: str | None = None
    year: int | None = None


class StoreUnitBody(BaseModel):
    args: StoreUnitArgs


class StoreUnitRequest(BaseModel):
    body: StoreUnitBody
