"""Tests for time features, hourly grain, and posted-vs-actual summaries."""

from __future__ import annotations

import pandas as pd

from wdw.features import add_time_features, hourly_aggregates
from wdw.model import posted_vs_actual
from wdw.sample_data import generate_sample_hourly
from wdw.typical import typical_day_curve


def test_add_time_features_weekend_and_hour() -> None:
    frame = pd.DataFrame(
        {
            "observed_at": [pd.Timestamp("2018-01-06 14:00:00")],  # Saturday
        }
    )
    out = add_time_features(frame)
    assert int(out.loc[0, "hour"]) == 14
    assert int(out.loc[0, "is_weekend"]) == 1
    assert int(out.loc[0, "weekday"]) == 5


def test_hourly_aggregates_median() -> None:
    waits = pd.DataFrame(
        {
            "attraction_key": ["pirates_of_caribbean"] * 4,
            "attraction_name": ["Pirates of the Caribbean"] * 4,
            "park_key": ["magic_kingdom"] * 4,
            "park_name": ["Magic Kingdom Park"] * 4,
            "live_entity_id": ["x"] * 4,
            "live_name": ["Pirates of the Caribbean"] * 4,
            "park_date": [pd.Timestamp("2018-01-01")] * 4,
            "observed_at": pd.to_datetime(
                [
                    "2018-01-01 10:05:00",
                    "2018-01-01 10:20:00",
                    "2018-01-01 10:40:00",
                    "2018-01-01 11:10:00",
                ]
            ),
            "posted_wait": [20, 30, 40, 50],
            "actual_wait": [10, 20, 20, 35],
        }
    )
    hourly = hourly_aggregates(waits)
    ten = hourly.loc[hourly["observed_at"] == pd.Timestamp("2018-01-01 10:00:00")].iloc[0]
    assert ten["posted_wait_median"] == 30
    assert ten["posted_n"] == 3
    assert ten["posted_minus_actual"] == 10


def test_sample_typical_day_peaks_midday() -> None:
    hourly = generate_sample_hourly(weeks=2)
    curve = typical_day_curve(hourly, "seven_dwarfs_train")
    midday = float(curve.loc[curve["hour"].between(11, 15), "posted_median"].mean())
    rope_drop = float(curve.loc[curve["hour"] == 8, "posted_median"].mean())
    assert midday > rope_drop


def test_closed_hours_plot_as_zero() -> None:
    hourly = pd.DataFrame(
        {
            "attraction_key": ["pirates_of_caribbean"] * 3,
            "attraction_name": ["Pirates of the Caribbean"] * 3,
            "park_name": ["Magic Kingdom Park"] * 3,
            "hour": [8, 14, 22],
            "posted_wait_median": [5.0, 40.0, pd.NA],
            "actual_wait_median": [3.0, 28.0, pd.NA],
        }
    )
    curve = typical_day_curve(hourly, "pirates_of_caribbean")
    assert list(curve["hour"])[:3] == [6, 7, 8]
    assert float(curve.loc[curve["hour"] == 6, "posted_median"].iloc[0]) == 0
    assert float(curve.loc[curve["hour"] == 6, "actual_median"].iloc[0]) == 0
    assert float(curve.loc[curve["hour"] == 22, "posted_median"].iloc[0]) == 0
    assert float(curve.loc[curve["hour"] == 14, "posted_median"].iloc[0]) == 40
    # Overnight hours sit at the end of a park day, not at 12 AM on the left.
    assert int(curve["hour"].iloc[-1]) == 2


def test_posted_waits_exceed_actual_on_sample() -> None:
    hourly = generate_sample_hourly(weeks=2)
    summary = posted_vs_actual(hourly)
    assert (summary["bias_mean"] > 0).all()
