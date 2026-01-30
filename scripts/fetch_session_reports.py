#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any


def _sha1_10(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _redacted(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    return f"<redacted len={len(value)} sha1={_sha1_10(value)}>"


def _format_ts(unix_s: float | None) -> str:
    if not unix_s:
        return "unknown"
    return dt.datetime.fromtimestamp(unix_s, tz=dt.timezone.utc).isoformat()


def _http_get_json(url: str, *, token: str | None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url=url, method="GET", headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")

    if not body.strip():
        return {}

    parsed = json.loads(body)
    return parsed if isinstance(parsed, dict) else {}


def _extract_messages(report: dict[str, Any]) -> tuple[list[str], list[str]]:
    history = report.get("chat_history")
    if not isinstance(history, dict):
        return ([], [])

    items = history.get("items")
    if not isinstance(items, list):
        return ([], [])

    user_msgs: list[str] = []
    assistant_msgs: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        role = item.get("role")
        content = item.get("content")

        text = ""
        if isinstance(content, list):
            parts = [c for c in content if isinstance(c, str)]
            text = "\n".join(parts)
        elif isinstance(content, str):
            text = content

        if not isinstance(text, str) or not text.strip():
            continue

        if role == "user":
            user_msgs.append(text.strip())
        elif role == "assistant":
            assistant_msgs.append(text.strip())

    return (user_msgs, assistant_msgs)


def _extract_realtime_ttft_s(report: dict[str, Any]) -> list[float]:
    events = report.get("events")
    if not isinstance(events, list):
        return []

    ttfts: list[float] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") != "metrics_collected":
            continue
        metrics = ev.get("metrics")
        if not isinstance(metrics, dict):
            continue
        if metrics.get("type") != "realtime_model_metrics":
            continue
        ttft = metrics.get("ttft")
        if isinstance(ttft, (int, float)) and ttft >= 0:
            ttfts.append(float(ttft))
    return ttfts


def _print_report_summary(
    *,
    room_name: str,
    received_at_unix_s: float | None,
    report: dict[str, Any],
    show_pii: bool,
) -> None:
    user_msgs, assistant_msgs = _extract_messages(report)
    ttfts = _extract_realtime_ttft_s(report)

    last_user = user_msgs[-1] if user_msgs else ""
    last_assistant = assistant_msgs[-1] if assistant_msgs else ""
    if not show_pii:
        last_user = _redacted(last_user)
        last_assistant = _redacted(last_assistant)

    ttft_summary = ""
    if ttfts:
        ttft_summary = f" ttft_s(min/avg/max)={min(ttfts):.2f}/{(sum(ttfts)/len(ttfts)):.2f}/{max(ttfts):.2f}"

    print(f"- room={room_name} received_at_utc={_format_ts(received_at_unix_s)}")
    print(f"  turns user_msgs={len(user_msgs)} assistant_msgs={len(assistant_msgs)}{ttft_summary}")
    if last_user:
        print(f"  last_user: {last_user}")
    if last_assistant:
        print(f"  last_assistant: {last_assistant}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch LiveKit session reports from the backend observability endpoint.\n"
            "Defaults to using SESSION_REPORTS_URL + SESSION_REPORTS_TOKEN env vars."
        )
    )
    parser.add_argument(
        "--url",
        help=(
            "Base session report URL (ex: https://<domain>/observability/session-report). "
            "Defaults to $SESSION_REPORTS_URL."
        ),
    )
    parser.add_argument("--token", help="Bearer token (defaults to $SESSION_REPORTS_TOKEN).")
    parser.add_argument("--limit", type=int, default=5, help="Number of recent rooms to fetch.")
    parser.add_argument("--room", help="Fetch a single room report by room name.")
    parser.add_argument(
        "--pii",
        action="store_true",
        help="Print full user/assistant messages (PII). Default redacts content.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw JSON for the requested report(s).",
    )

    args = parser.parse_args(argv)
    base_url = (args.url or os.getenv("SESSION_REPORTS_URL", "")).strip()
    if not base_url:
        print("error: missing --url (or set SESSION_REPORTS_URL)", file=sys.stderr)
        return 2

    token = (args.token or os.getenv("SESSION_REPORTS_TOKEN", "")).strip() or None

    if args.room:
        room_name = args.room
        room_url = base_url.rstrip("/") + "/" + urllib.parse.quote(room_name, safe="")
        payload = _http_get_json(room_url, token=token)
        if args.raw:
            print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))
            return 0

        report = payload.get("report") if isinstance(payload, dict) else None
        if not isinstance(report, dict):
            print(f"error: no report found for room={room_name}", file=sys.stderr)
            return 1

        received_at = payload.get("received_at_unix_s")
        received_at_unix_s = float(received_at) if isinstance(received_at, (int, float)) else None
        _print_report_summary(
            room_name=room_name,
            received_at_unix_s=received_at_unix_s,
            report=report,
            show_pii=args.pii,
        )
        return 0

    list_url = base_url.rstrip("/") + "?" + urllib.parse.urlencode({"limit": args.limit})
    listing = _http_get_json(list_url, token=token)
    reports = listing.get("reports")
    if not isinstance(reports, list):
        print("error: backend did not return reports list", file=sys.stderr)
        return 1

    if args.raw:
        print(json.dumps(listing, indent=2, ensure_ascii=True, default=str))
        return 0

    if not reports:
        print("No session reports found (note: reports appear only after the call ends).")
        return 0

    for entry in reports:
        if not isinstance(entry, dict):
            continue
        room_name = entry.get("room_name")
        if not isinstance(room_name, str) or not room_name.strip():
            continue

        room_url = base_url.rstrip("/") + "/" + urllib.parse.quote(room_name, safe="")
        payload = _http_get_json(room_url, token=token)
        report = payload.get("report") if isinstance(payload, dict) else None
        if not isinstance(report, dict):
            continue

        received_at = payload.get("received_at_unix_s")
        received_at_unix_s = float(received_at) if isinstance(received_at, (int, float)) else None
        _print_report_summary(
            room_name=room_name,
            received_at_unix_s=received_at_unix_s,
            report=report,
            show_pii=args.pii,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

