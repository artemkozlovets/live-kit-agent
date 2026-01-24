from pydantic import BaseModel


class ValidateVinArgs(BaseModel):
    vin_number: str


class ValidateVinBody(BaseModel):
    args: ValidateVinArgs


class ValidateVinRequest(BaseModel):
    body: ValidateVinBody
