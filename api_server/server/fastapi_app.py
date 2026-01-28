import json
import logging
import os
import traceback
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI

from api_server.server.routers.customer import router as customer_router
from api_server.server.routers.service_order import router as service_order_router
from api_server.server.routers.unit import router as unit_router
from api_server.server.routers.validation import router as validation_router
from api_server.observability.router import router as observability_router
from api_server.tools.router import router as tools_router

if not os.getenv("PYTEST_CURRENT_TEST"):
    load_dotenv()


_LOG_RECORD_BUILTINS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
}


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts_unix_s": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_BUILTINS:
                continue
            extra[key] = value
        if extra:
            payload["extra"] = extra

        if record.exc_info:
            payload["exc"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(payload, ensure_ascii=True, default=str)


def _maybe_enable_local_file_logging() -> None:
    local_dir = os.getenv("LOCAL_OBSERVABILITY_DIR", "").strip()
    if not local_dir:
        return

    os.makedirs(local_dir, exist_ok=True)
    log_path = os.path.join(local_dir, "backend.log.jsonl")

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(_JsonLogFormatter())

    # Note: log volume is controlled by LOG_LEVEL / uvicorn log config.
    handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    # Avoid duplicate handlers when re-imported in tests.
    if any(getattr(h, "baseFilename", None) == handler.baseFilename for h in root.handlers):
        return

    root.addHandler(handler)

    # Uvicorn loggers may have propagate=False, so attach explicitly when needed.
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not logger.propagate and not any(
            getattr(h, "baseFilename", None) == handler.baseFilename for h in logger.handlers
        ):
            logger.addHandler(handler)


if not os.getenv("PYTEST_CURRENT_TEST"):
    _maybe_enable_local_file_logging()

app = FastAPI()

app.include_router(tools_router)
app.include_router(observability_router)
app.include_router(validation_router)
app.include_router(customer_router)
app.include_router(unit_router)
app.include_router(service_order_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/health/env")
def env_health_check() -> dict[str, bool]:
    """Report whether optional env vars are loaded (no secrets)."""
    # Note: backend "Gemini" features use the Google Generative Language API key. We
    # support both variable names to reduce local dev confusion.
    gemini_api_key_present = bool(
        (os.getenv("GEMINI_API_KEY") or "").strip()
        or (os.getenv("GOOGLE_API_KEY") or "").strip()
        or (os.getenv("GEMINI_GUARD_API_KEY") or "").strip()
    )
    return {
        "google_api_key_loaded": bool(os.getenv("GOOGLE_API_KEY")),
        "gemini_api_key_loaded": gemini_api_key_present,
        "gemini_guard_api_key_loaded": bool(os.getenv("GEMINI_GUARD_API_KEY")),
    }
