from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from api_server.observability.session_report_store import SessionReportStore

router = APIRouter(prefix="/observability")

# Reason: singleton store shared across all requests (MVP single-instance)
_session_report_store = SessionReportStore()

# Reason: expose store for tests
session_report_store = _session_report_store


def _require_bearer_token_if_configured(request: Request) -> None:
    expected = os.getenv("SESSION_REPORTS_TOKEN", "").strip()
    if not expected:
        return

    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.post("/session-report")
async def ingest_session_report(request: Request) -> dict[str, bool]:
    _require_bearer_token_if_configured(request)

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    room_name = payload.get("room_name")
    report = payload.get("report")
    if not isinstance(room_name, str) or not room_name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="room_name is required")
    if not isinstance(report, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="report must be an object")

    _session_report_store.set(
        room_name.strip(),
        {
            "report": dict(report),
            "received_at_unix_s": time.time(),
        },
    )
    return {"ok": True}


@router.get("/session-report/{room_name}")
async def get_session_report(room_name: str, request: Request) -> dict[str, Any]:
    _require_bearer_token_if_configured(request)

    report = _session_report_store.get(room_name)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session report not found")

    return {
        "room_name": room_name,
        "report": report.get("report", {}),
        "received_at_unix_s": report.get("received_at_unix_s"),
    }


@router.get("/session-report")
async def list_session_reports(
    request: Request,
    limit: int = Query(default=20, ge=0, le=200),
) -> dict[str, Any]:
    _require_bearer_token_if_configured(request)
    return {"reports": _session_report_store.list(limit=limit)}
