from pydantic import BaseModel


class CheckVinArgs(BaseModel):
    vin_number: str


class CheckVinBody(BaseModel):
    args: CheckVinArgs


class CheckVinRequest(BaseModel):
    body: CheckVinBody
