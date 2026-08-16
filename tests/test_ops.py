"""Shift-console attention rules."""

from __future__ import annotations

import pandas as pd

from wdw.ops import (
    STACK_THRESHOLD,
    attention_queue,
    classify_attraction,
    current_vs_typical,
    format_lead_minutes,
    overlapping_hours,
    return_pressure_kpis,
    return_time_pressure,
    return_windows_by_hour,
)


def test_down_is_critical() -> None:
    item = classify_attraction(
        {
            "entity_name": "Space Mountain",
            "park_name": "Magic Kingdom Park",
            "status": "DOWN",
            "standby_wait": None,
            "park_has_open": True,
        }
    )
    assert item is not None
    assert item["severity"] == "critical"
    assert item["signal"] == "Down"


def test_hot_vs_expected_is_high() -> None:
    item = classify_attraction(
        {
            "entity_name": "Seven Dwarfs Mine Train",
            "park_name": "Magic Kingdom Park",
            "status": "OPERATING",
            "standby_wait": 85,
            "delta_vs_expected": 30,
            "park_has_open": True,
        }
    )
    assert item is not None
    assert item["severity"] == "high"
    assert "above expected" in item["signal"]


def test_quiet_operating_ride_is_silent() -> None:
    item = classify_attraction(
        {
            "entity_name": "Pirates of the Caribbean",
            "park_name": "Magic Kingdom Park",
            "status": "OPERATING",
            "standby_wait": 20,
            "delta_vs_expected": 2,
            "park_has_open": True,
        }
    )
    assert item is None


def test_attention_queue_ranks_downs_first() -> None:
    live = pd.DataFrame(
        {
            "entity_id": ["a", "b", "c"],
            "entity_name": ["Ride A", "Ride B", "Ride C"],
            "entity_type": ["ATTRACTION", "ATTRACTION", "ATTRACTION"],
            "park_name": ["Magic Kingdom Park"] * 3,
            "status": ["OPERATING", "DOWN", "OPERATING"],
            "standby_wait": [20, None, 95],
        }
    )
    scored = pd.DataFrame(
        {
            "entity_id": ["a", "c"],
            "expected_wait": [18.0, 40.0],
            "delta_vs_expected": [2.0, 55.0],
        }
    )
    queue = attention_queue(live, scored)
    assert queue.iloc[0]["attraction"] == "Ride B"
    assert queue.iloc[0]["severity"] == "critical"
    assert "Ride C" in set(queue["attraction"])
    assert "Ride A" not in set(queue["attraction"])


def test_current_vs_typical_delta() -> None:
    curve = pd.DataFrame({"hour": [10, 11, 12], "posted_median": [15.0, 25.0, 40.0], "n": [4, 4, 4]})
    result = current_vs_typical(curve, live_wait=55, hour=12)
    assert result["typical"] == 40
    assert result["live"] == 55
    assert result["delta"] == 15


def test_current_vs_typical_skips_empty_hours() -> None:
    curve = pd.DataFrame({"hour": [12], "posted_median": [0.0], "n": [0]})
    result = current_vs_typical(curve, live_wait=35, hour=12)
    assert result["typical"] is None
    assert result["delta"] is None


def _live_row(**overrides) -> dict:
    row = {
        "entity_type": "ATTRACTION",
        "entity_name": "Space Mountain",
        "park_name": "Magic Kingdom Park",
        "status": "OPERATING",
        "standby_wait": 45,
        "return_time_state": None,
        "return_start": None,
        "return_end": None,
        "paid_return_state": None,
        "paid_return_start": None,
        "paid_return_end": None,
    }
    row.update(overrides)
    return row


def test_available_return_lead_minutes() -> None:
    now = pd.Timestamp("2026-08-16 12:00:00", tz="America/New_York")
    live = pd.DataFrame(
        [
            _live_row(
                return_time_state="AVAILABLE",
                return_start="2026-08-16T14:00:00-04:00",
                return_end="2026-08-16T15:00:00-04:00",
            )
        ]
    )
    out = return_time_pressure(live, now=now)
    assert len(out) == 1
    assert out.iloc[0]["inventory"] == "available"
    assert out.iloc[0]["product"] == "Lightning Lane"
    assert out.iloc[0]["lead_minutes"] == 120
    assert int(out.iloc[0]["hour"]) == 14


def test_finished_return_is_exhausted() -> None:
    now = pd.Timestamp("2026-08-16 12:00:00", tz="America/New_York")
    live = pd.DataFrame([_live_row(entity_name="Pirates of the Caribbean", return_time_state="FINISHED")])
    out = return_time_pressure(live, now=now)
    assert len(out) == 1
    assert out.iloc[0]["inventory"] == "exhausted"
    assert pd.isna(out.iloc[0]["lead_minutes"]) or out.iloc[0]["lead_minutes"] is None
    assert not bool(out.iloc[0]["stacked"])


def test_quiet_ride_has_no_return_pressure() -> None:
    now = pd.Timestamp("2026-08-16 12:00:00", tz="America/New_York")
    live = pd.DataFrame([_live_row(entity_name="Jungle Cruise")])
    out = return_time_pressure(live, now=now)
    assert out.empty


def test_paid_return_is_a_separate_row() -> None:
    now = pd.Timestamp("2026-08-16 12:00:00", tz="America/New_York")
    live = pd.DataFrame(
        [
            _live_row(
                entity_name="TRON Lightcycle / Run",
                return_time_state="FINISHED",
                paid_return_state="AVAILABLE",
                paid_return_start="2026-08-16T16:30:00-04:00",
                paid_return_end="2026-08-16T17:30:00-04:00",
            )
        ]
    )
    out = return_time_pressure(live, now=now)
    products = set(out["product"])
    assert products == {"Lightning Lane", "Individual Lightning Lane"}
    paid = out.loc[out["product"] == "Individual Lightning Lane"].iloc[0]
    assert paid["inventory"] == "available"
    assert paid["lead_minutes"] == 270


def test_same_hour_windows_stack_within_a_park() -> None:
    now = pd.Timestamp("2026-08-16 10:00:00", tz="America/New_York")
    names = ["Space Mountain", "Big Thunder Mountain Railroad", "Seven Dwarfs Mine Train"]
    assert len(names) >= STACK_THRESHOLD
    live = pd.DataFrame(
        [
            _live_row(
                entity_name=name,
                return_time_state="AVAILABLE",
                return_start="2026-08-16T16:00:00-04:00",
                return_end="2026-08-16T17:00:00-04:00",
            )
            for name in names
        ]
        + [
            _live_row(
                entity_name="Test Track",
                park_name="EPCOT",
                return_time_state="AVAILABLE",
                return_start="2026-08-16T16:15:00-04:00",
                return_end="2026-08-16T17:15:00-04:00",
            )
        ]
    )
    out = return_time_pressure(live, now=now)
    mk = out.loc[out["park_name"] == "Magic Kingdom Park"]
    epcot = out.loc[out["park_name"] == "EPCOT"]
    assert set(mk["stacked"]) == {True}
    assert int(mk["windows_in_hour"].iloc[0]) == 3
    assert set(epcot["stacked"]) == {False}
    assert int(epcot["windows_in_hour"].iloc[0]) == 1
    counts = return_windows_by_hour(out)
    mk_hour = counts.loc[(counts["park_name"] == "Magic Kingdom Park") & (counts["hour"] == 16)]
    assert int(mk_hour["attractions"].iloc[0]) == 3
    overlap = overlapping_hours(out)
    assert len(overlap) == 1
    assert overlap.iloc[0]["park_name"] == "Magic Kingdom Park"
    assert int(overlap.iloc[0]["hour"]) == 16
    assert int(overlap.iloc[0]["attractions"]) == 3
    kpis = return_pressure_kpis(out)
    assert kpis["stacked_hours"] == 1
    assert kpis["busiest_count"] == 3
    assert kpis["busiest_hour"] == 16
    assert kpis["busiest_park"] == "Magic Kingdom Park"


def test_return_pressure_kpis_use_farthest_available_window() -> None:
    now = pd.Timestamp("2026-08-16 12:00:00", tz="America/New_York")
    live = pd.DataFrame(
        [
            _live_row(
                return_time_state="AVAILABLE",
                return_start="2026-08-16T14:00:00-04:00",
                return_end="2026-08-16T15:00:00-04:00",
            ),
            _live_row(
                entity_name="Haunted Mansion",
                return_time_state="AVAILABLE",
                return_start="2026-08-16T18:00:00-04:00",
                return_end="2026-08-16T19:00:00-04:00",
            ),
            _live_row(entity_name="Pirates of the Caribbean", return_time_state="FINISHED"),
        ]
    )
    kpis = return_pressure_kpis(return_time_pressure(live, now=now))
    assert kpis["available"] == 2
    assert kpis["exhausted"] == 1
    assert kpis["farthest_minutes"] == 360
    assert kpis["farthest_attraction"] == "Haunted Mansion"
    assert kpis["stacked_hours"] == 0


def test_format_lead_minutes() -> None:
    assert format_lead_minutes(120) == "2h"
    assert format_lead_minutes(135) == "2h 15m"
    assert format_lead_minutes(45) == "45 min"
    assert format_lead_minutes(-10) == "Now"
    assert format_lead_minutes(None) == "n/a"
