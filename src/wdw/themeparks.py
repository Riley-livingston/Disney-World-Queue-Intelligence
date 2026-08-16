"""ThemeParks.wiki client for Walt Disney World live waits and schedules."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from wdw.config import (
    LIVE_CACHE_SECONDS,
    MAX_RETRIES,
    MIN_REQUEST_INTERVAL_SECONDS,
    THEMEPARKS_BASE_URL,
    parks,
)

CREDIT = "Powered by ThemeParks.wiki"


class ThemeParksError(RuntimeError):
    """Raised when the ThemeParks.wiki API cannot be reached or returns an error."""


class ThemeParksClient:
    """Small HTTP client with a 5-minute in-memory cache and 429 backoff."""

    def __init__(
        self,
        base_url: str = THEMEPARKS_BASE_URL,
        timeout: float = 30.0,
        cache_seconds: int = LIVE_CACHE_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._last_request_at: float = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    def _get(self, path: str) -> dict[str, Any]:
        cached = self._cache.get(path)
        now = datetime.now(UTC)
        if cached and now - cached[0] < timedelta(seconds=self.cache_seconds):
            return cached[1]

        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            self._throttle()
            try:
                with httpx.Client(timeout=self.timeout, headers={"Accept": "application/json"}) as client:
                    response = client.get(url)
                self._last_request_at = time.monotonic()
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    time.sleep(retry_after)
                    continue
                response.raise_for_status()
                payload = response.json()
                self._cache[path] = (now, payload)
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))

        raise ThemeParksError(f"Failed to fetch {url}") from last_error

    def entity_live(self, entity_id: str) -> dict[str, Any]:
        return self._get(f"/entity/{entity_id}/live")

    def entity_schedule(self, entity_id: str) -> dict[str, Any]:
        return self._get(f"/entity/{entity_id}/schedule")

    def wdw_live(self) -> list[dict[str, Any]]:
        """Live wait payload for the four WDW theme parks."""
        fetched_at = datetime.now(UTC).isoformat()
        snapshots: list[dict[str, Any]] = []
        for park_key, spec in parks().items():
            payload = self.entity_live(spec["entity_id"])
            snapshots.append(
                {
                    "park_key": park_key,
                    "park_name": spec["name"],
                    "park_id": spec["entity_id"],
                    "fetched_at": fetched_at,
                    "payload": payload,
                }
            )
        return snapshots

    def wdw_schedules(self) -> list[dict[str, Any]]:
        fetched_at = datetime.now(UTC).isoformat()
        snapshots: list[dict[str, Any]] = []
        for park_key, spec in parks().items():
            payload = self.entity_schedule(spec["entity_id"])
            snapshots.append(
                {
                    "park_key": park_key,
                    "park_name": spec["name"],
                    "park_id": spec["entity_id"],
                    "fetched_at": fetched_at,
                    "payload": payload,
                }
            )
        return snapshots


def flatten_live(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn nested ThemeParks live payloads into one row per attraction/show."""
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        payload = snapshot["payload"]
        for entry in payload.get("liveData", []):
            queue = entry.get("queue") or {}
            standby = queue.get("STANDBY") or {}
            single_rider = queue.get("SINGLE_RIDER") or {}
            return_time = queue.get("RETURN_TIME") or {}
            paid_return = queue.get("PAID_RETURN_TIME") or {}
            boarding = queue.get("BOARDING_GROUP") or {}
            hours = entry.get("operatingHours") or []
            operating = next((h for h in hours if h.get("type") == "Operating"), None)
            forecast = entry.get("forecast") or []
            rows.append(
                {
                    "fetched_at": snapshot["fetched_at"],
                    "park_key": snapshot["park_key"],
                    "park_name": snapshot["park_name"],
                    "park_id": snapshot["park_id"],
                    "entity_id": entry.get("id"),
                    "entity_name": entry.get("name"),
                    "entity_type": entry.get("entityType"),
                    "status": entry.get("status"),
                    "standby_wait": standby.get("waitTime"),
                    "single_rider_wait": single_rider.get("waitTime"),
                    "return_time_state": return_time.get("state"),
                    "return_start": return_time.get("returnStart"),
                    "return_end": return_time.get("returnEnd"),
                    "paid_return_state": paid_return.get("state"),
                    "paid_return_start": paid_return.get("returnStart"),
                    "paid_return_end": paid_return.get("returnEnd"),
                    "boarding_status": boarding.get("allocationStatus"),
                    "last_updated": entry.get("lastUpdated"),
                    "opens_at": (operating or {}).get("startTime"),
                    "closes_at": (operating or {}).get("endTime"),
                    "forecast": forecast,
                }
            )
    return rows


def flatten_schedules(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        payload = snapshot["payload"]
        for entry in payload.get("schedule", []):
            rows.append(
                {
                    "fetched_at": snapshot["fetched_at"],
                    "park_key": snapshot["park_key"],
                    "park_name": snapshot["park_name"],
                    "park_id": snapshot["park_id"],
                    "date": entry.get("date"),
                    "type": entry.get("type"),
                    "description": entry.get("description"),
                    "opening_time": entry.get("openingTime"),
                    "closing_time": entry.get("closingTime"),
                }
            )
    return rows
