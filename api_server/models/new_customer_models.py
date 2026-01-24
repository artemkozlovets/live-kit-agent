from pydantic import BaseModel


class NewCustomerArgs(BaseModel):
    first_name: str
    last_name: str
    company_name: str
    email_address: str | None = None
    phone_number: str
    customer_position: str | None = None
    marketing_source: str | None = None
    streetAddress: str
    city: str
    state: str
    country: str | None = None
    postalCode: str


class NewCustomerBody(BaseModel):
    args: NewCustomerArgs


class NewCustomerRequest(BaseModel):
    body: NewCustomerBody
