"""Shift-console attention rules."""

from __future__ import annotations

import pandas as pd

from wdw.ops import attention_queue, classify_attraction, current_vs_typical


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
    curve = pd.DataFrame({"hour": [10, 11, 12], "posted_median": [15.0, 25.0, 40.0]})
    result = current_vs_typical(curve, live_wait=55, hour=12)
    assert result["typical"] == 40
    assert result["live"] == 55
    assert result["delta"] == 15
