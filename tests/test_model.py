"""Tests for historical expected wait."""

from __future__ import annotations

import pandas as pd

from wdw.model import expected_wait
from wdw.sample_data import generate_sample_hourly


def test_expected_wait_scores_mapped_headliners() -> None:
    hourly = generate_sample_hourly(weeks=2)
    spec = hourly.dropna(subset=["live_entity_id"]).iloc[0]
    live = pd.DataFrame(
        {
            "entity_id": [spec["live_entity_id"]],
            "entity_name": [spec["attraction_name"]],
            "park_name": [spec["park_name"]],
            "standby_wait": [90.0],
        }
    )
    scored = expected_wait(live, hourly)
    assert len(scored) == 1
    assert pd.notna(scored["expected_wait"].iloc[0])
    assert float(scored["delta_vs_expected"].iloc[0]) == 90.0 - float(scored["expected_wait"].iloc[0])


def test_expected_wait_drops_unmapped_rides() -> None:
    hourly = generate_sample_hourly(weeks=1)
    live = pd.DataFrame(
        {
            "entity_id": ["not-a-touringplans-ride"],
            "entity_name": ["Jungle Cruise"],
            "park_name": ["Magic Kingdom Park"],
            "standby_wait": [40],
        }
    )
    scored = expected_wait(live, hourly)
    assert scored.empty
