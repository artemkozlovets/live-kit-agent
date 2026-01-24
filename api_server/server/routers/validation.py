from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from api_server.models.phone_verify_models import PhoneVerifyRequest
from api_server.models.validate_vin_models import ValidateVinRequest
from api_server.utils.phone_formatting import normalize_us_phone_number
from api_server.utils.vin_formatting import VIN_NUMBER_REGEX, normalize_vin_number

router = APIRouter()


@router.post("/phoneVerify")
def phone_verify(request: PhoneVerifyRequest):
    phone_verify_args = request.body.args

    normalized_phone_number = normalize_us_phone_number(phone_verify_args.phone_number)
    if normalized_phone_number is not None:
        return {"is_phone_valid": True}

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"is_phone_valid": False},
    )


@router.post("/validateVIN")
def validate_vin(request: ValidateVinRequest):
    validate_vin_args = request.body.args

    cleaned_vin_number = normalize_vin_number(validate_vin_args.vin_number)
    is_vin_valid = bool(VIN_NUMBER_REGEX.fullmatch(cleaned_vin_number))

    if is_vin_valid:
        return {"is_vin_valid": True, "vin_number": cleaned_vin_number}

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"is_vin_valid": False, "vin_number": cleaned_vin_number},
    )

