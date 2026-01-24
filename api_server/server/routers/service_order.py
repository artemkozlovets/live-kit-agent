from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from api_server.models.store_service_order_models import StoreServiceOrderRequest
from api_server.server.dependencies import DatabaseClient, get_database_client

router = APIRouter()


@router.post("/storeServiceOrder")
def store_service_order(
    request: StoreServiceOrderRequest,
    database_client: DatabaseClient = Depends(get_database_client),
):
    store_service_order_args = request.body.args

    customer_exists = database_client.customer_exists(store_service_order_args)
    if not customer_exists:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "Customer not found"},
        )

    unit_record = database_client.find_unit_for_service_order(store_service_order_args)
    if unit_record is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "Unit not found"},
        )

    unit_belongs_to_customer = unit_record.customer_id == store_service_order_args.customer_id
    if not unit_belongs_to_customer:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Unit does not belong to customer"},
        )

    service_order_id = database_client.create_service_order(store_service_order_args)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"service_order_id": service_order_id},
    )

