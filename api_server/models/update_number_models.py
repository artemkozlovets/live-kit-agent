from pydantic import BaseModel


class UpdateNumberArgs(BaseModel):
    first_name: str
    last_name: str


class UpdateNumberBody(BaseModel):
    args: UpdateNumberArgs


class UpdateNumberRequest(BaseModel):
    new_phone_number: str
    body: UpdateNumberBody

