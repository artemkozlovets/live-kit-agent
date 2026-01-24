from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from api_server.models.check_vin_models import CheckVinRequest
from api_server.models.store_unit_models import StoreUnitRequest
from api_server.server.dependencies import DatabaseClient, get_database_client
from api_server.utils.phone_formatting import normalize_us_phone_number
from api_server.utils.vin_formatting import VIN_NUMBER_REGEX, normalize_vin_number

router = APIRouter()


@router.post("/checkVin")
def check_vin(
    request: CheckVinRequest,
    database_client: DatabaseClient = Depends(get_database_client),
):
    check_vin_args = request.body.args
    cleaned_vin_number = normalize_vin_number(check_vin_args.vin_number)

    is_vin_format_valid = bool(VIN_NUMBER_REGEX.fullmatch(cleaned_vin_number))
    if not is_vin_format_valid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "vin_number": cleaned_vin_number,
                "is_in_database": False,
            },
        )

    check_vin_args_with_cleaned_vin_number = check_vin_args.model_copy(
        update={"vin_number": cleaned_vin_number}
    )

    unit_record = database_client.find_unit_by_vin_number(check_vin_args_with_cleaned_vin_number)
    if unit_record is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "vin_number": cleaned_vin_number,
                "unit_number": "",
                "is_in_database": False,
            },
        )

    return {
        "vin_number": cleaned_vin_number,
        "unit_number": unit_record.unit_number,
        "is_in_database": True,
    }


@router.post("/storeUnit")
def store_unit(
    request: StoreUnitRequest,
    database_client: DatabaseClient = Depends(get_database_client),
):
    store_unit_args = request.body.args

    normalized_phone_number = normalize_us_phone_number(store_unit_args.phone_number)
    if normalized_phone_number is None:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Invalid phone number"},
        )

    cleaned_vin_number = normalize_vin_number(store_unit_args.vin_number)
    store_unit_args_with_cleaned_values = store_unit_args.model_copy(
        update={
            "phone_number": normalized_phone_number,
            "vin_number": cleaned_vin_number,
        }
    )

    customer_id = database_client.find_customer_for_unit_creation(store_unit_args_with_cleaned_values)
    if customer_id is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "Customer not found"},
        )

    unit_id = database_client.create_unit(store_unit_args_with_cleaned_values, customer_id)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"customer_id": customer_id, "unit_id": unit_id},
    )

