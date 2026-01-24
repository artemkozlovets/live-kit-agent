from pydantic import BaseModel


class InboundArgs(BaseModel):
    phone_number: str


class InboundBody(BaseModel):
    args: InboundArgs


class InboundRequest(BaseModel):
    body: InboundBody
