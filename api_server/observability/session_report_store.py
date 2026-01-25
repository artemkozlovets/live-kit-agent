"""In-memory session report store keyed by room_name.

Reason: this is an MVP bridge to access LiveKit Agent session reports without
opening the LiveKit Cloud UI. It is not durable across restarts.
"""

from __future__ import annotations

from typing import Any


class SessionReportStore:
    def __init__(self) -> None:
        self._by_room_name: dict[str, dict[str, Any]] = {}

    def get(self, room_name: str) -> dict[str, Any] | None:
        report = self._by_room_name.get(room_name)
        return dict(report) if isinstance(report, dict) else None

    def set(self, room_name: str, report: dict[str, Any]) -> None:
        self._by_room_name[room_name] = dict(report)

    def clear(self, room_name: str) -> None:
        self._by_room_name.pop(room_name, None)

    def list(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Return stored reports (metadata only) sorted by received time desc."""

        items: list[dict[str, Any]] = []
        for room_name, entry in self._by_room_name.items():
            received_at = None
            if isinstance(entry, dict):
                received_at = entry.get("received_at_unix_s")
            items.append({"room_name": room_name, "received_at_unix_s": received_at})

        def _sort_key(item: dict[str, Any]) -> float:
            value = item.get("received_at_unix_s")
            return float(value) if isinstance(value, (int, float)) else 0.0

        items.sort(key=_sort_key, reverse=True)
        if limit is not None:
            items = items[: max(limit, 0)]
        return items
