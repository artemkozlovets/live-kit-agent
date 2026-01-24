from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from api_server.models.inbound_models import InboundRequest
from api_server.models.new_customer_models import NewCustomerRequest
from api_server.models.update_number_models import UpdateNumberRequest
from api_server.server.dependencies import DatabaseClient, get_database_client
from api_server.utils.phone_formatting import normalize_us_phone_number

router = APIRouter()


@router.post("/inbound")
def inbound(
    request: InboundRequest,
    database_client: DatabaseClient = Depends(get_database_client),
):
    inbound_args = request.body.args

    customer_record = database_client.find_customer_by_phone_number(inbound_args)
    if customer_record is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"customer_exists": False},
        )

    return {
        "customer_exists": True,
        "customer_name": customer_record.customer_name,
        "customer_id": customer_record.customer_id,
        "phone_number": customer_record.phone_number,
    }


@router.post("/newCustomer")
def new_customer(
    request: NewCustomerRequest,
    database_client: DatabaseClient = Depends(get_database_client),
):
    new_customer_args = request.body.args

    normalized_phone_number = normalize_us_phone_number(new_customer_args.phone_number)
    if normalized_phone_number is None:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Invalid phone number"},
        )

    new_customer_args_with_normalized_phone_number = new_customer_args.model_copy(
        update={"phone_number": normalized_phone_number}
    )

    customer_id = database_client.create_customer(new_customer_args_with_normalized_phone_number)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"customer_id": customer_id},
    )


@router.post("/updateNumber")
def update_number(
    request: UpdateNumberRequest,
    database_client: DatabaseClient = Depends(get_database_client),
):
    normalized_phone_number = normalize_us_phone_number(request.new_phone_number)
    if normalized_phone_number is None:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Invalid phone number"},
        )

    request_with_normalized_phone_number = request.model_copy(
        update={"new_phone_number": normalized_phone_number}
    )

    customer_id = database_client.update_customer_phone_number(request_with_normalized_phone_number)
    if customer_id is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "Customer not found"},
        )

    return {"customer_id": customer_id}

