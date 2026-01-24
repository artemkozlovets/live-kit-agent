from pydantic import BaseModel


class StoreServiceOrderArgs(BaseModel):
    customer_id: str
    unit_id: str
    service_location: str | None = None
    service_complaint: str | None = None


class StoreServiceOrderBody(BaseModel):
    args: StoreServiceOrderArgs


class StoreServiceOrderRequest(BaseModel):
    body: StoreServiceOrderBody
