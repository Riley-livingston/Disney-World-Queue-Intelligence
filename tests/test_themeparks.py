"""Tests for ThemeParks.wiki payload flattening and client cache."""

from __future__ import annotations

from wdw.themeparks import ThemeParksClient, flatten_live, flatten_schedules

LIVE_FIXTURE = [
    {
        "park_key": "magic_kingdom",
        "park_name": "Magic Kingdom Park",
        "park_id": "75ea578a-adc8-4116-a54d-dccb60765ef9",
        "fetched_at": "2026-08-16T00:00:00+00:00",
        "payload": {
            "liveData": [
                {
                    "id": "abc",
                    "name": "Space Mountain",
                    "entityType": "ATTRACTION",
                    "status": "OPERATING",
                    "queue": {
                        "STANDBY": {"waitTime": 45},
                        "RETURN_TIME": {
                            "state": "AVAILABLE",
                            "returnStart": "2026-08-15T14:00:00-04:00",
                            "returnEnd": "2026-08-15T15:00:00-04:00",
                        },
                    },
                    "operatingHours": [
                        {
                            "type": "Operating",
                            "startTime": "2026-08-15T08:00:00-04:00",
                            "endTime": "2026-08-15T23:00:00-04:00",
                        }
                    ],
                    "lastUpdated": "2026-08-15T18:00:00Z",
                    "forecast": [{"time": "2026-08-15T18:00:00-04:00", "waitTime": 40}],
                },
                {
                    "id": "def",
                    "name": "Haunted Mansion",
                    "entityType": "ATTRACTION",
                    "status": "DOWN",
                    "queue": {"STANDBY": {"waitTime": None}},
                    "lastUpdated": "2026-08-15T18:01:00Z",
                },
            ]
        },
    }
]


def test_flatten_live_standby_and_return_time() -> None:
    rows = flatten_live(LIVE_FIXTURE)
    assert len(rows) == 2
    space = next(r for r in rows if r["entity_name"] == "Space Mountain")
    assert space["standby_wait"] == 45
    assert space["status"] == "OPERATING"
    assert space["return_time_state"] == "AVAILABLE"
    assert space["opens_at"].startswith("2026-08-15T08:00")
    haunted = next(r for r in rows if r["entity_name"] == "Haunted Mansion")
    assert haunted["status"] == "DOWN"
    assert haunted["standby_wait"] is None


def test_flatten_schedules() -> None:
    rows = flatten_schedules(
        [
            {
                "park_key": "epcot",
                "park_name": "EPCOT",
                "park_id": "x",
                "fetched_at": "t",
                "payload": {
                    "schedule": [
                        {
                            "date": "2026-08-15",
                            "type": "OPERATING",
                            "openingTime": "2026-08-15T09:00:00-04:00",
                            "closingTime": "2026-08-15T21:00:00-04:00",
                        },
                        {
                            "date": "2026-08-15",
                            "type": "TICKETED_EVENT",
                            "description": "Early Entry",
                            "openingTime": "2026-08-15T08:30:00-04:00",
                            "closingTime": "2026-08-15T09:00:00-04:00",
                        },
                    ]
                },
            }
        ]
    )
    assert len(rows) == 2
    assert rows[1]["description"] == "Early Entry"


def test_client_cache_avoids_second_http(monkeypatch) -> None:
    client = ThemeParksClient(cache_seconds=300)
    calls = {"n": 0}

    class FakeResponse:
        status_code = 200
        headers: dict = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"ok": True}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url: str):
            calls["n"] += 1
            return FakeResponse()

    monkeypatch.setattr("wdw.themeparks.httpx.Client", FakeClient)
    first = client.entity_live("park-1")
    second = client.entity_live("park-1")
    assert first == second == {"ok": True}
    assert calls["n"] == 1
