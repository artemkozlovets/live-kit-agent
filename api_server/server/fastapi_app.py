from fastapi import FastAPI

from api_server.server.routers.customer import router as customer_router
from api_server.server.routers.service_order import router as service_order_router
from api_server.server.routers.unit import router as unit_router
from api_server.server.routers.validation import router as validation_router
from api_server.vapi.router import vapi_router

app = FastAPI()

app.include_router(vapi_router, prefix="/vapi")
app.include_router(validation_router)
app.include_router(customer_router)
app.include_router(unit_router)
app.include_router(service_order_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}
