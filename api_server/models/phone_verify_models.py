from pydantic import BaseModel


class PhoneVerifyArgs(BaseModel):
    phone_number: str


class PhoneVerifyBody(BaseModel):
    args: PhoneVerifyArgs


class PhoneVerifyRequest(BaseModel):
    body: PhoneVerifyBody

