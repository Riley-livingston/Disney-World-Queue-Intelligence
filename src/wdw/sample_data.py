"""Compact offline hourly table so the app and tests run without the full CSVs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from wdw.config import SAMPLE_HOURLY_PARQUET, attractions, parks
from wdw.features import add_time_features

# Typical midday posted waits (minutes) from public TouringPlans-style reporting.
MIDDAY_POSTED = {
    "pirates_of_caribbean": 28,
    "seven_dwarfs_train": 85,
    "splash_mountain": 42,
    "soarin": 48,
    "spaceship_earth": 22,
    "rock_n_rollercoaster": 55,
    "toy_story_mania": 50,
    "slinky_dog": 70,
    "alien_saucers": 32,
    "dinosaur": 30,
    "expedition_everest": 40,
    "kilimanjaro_safaris": 38,
    "navi_river": 55,
    "flight_of_passage": 95,
}

# Posted waits run hotter than actual waits — the guest-communication buffer.
POSTED_BIAS = {
    "pirates_of_caribbean": 8,
    "seven_dwarfs_train": 16,
    "splash_mountain": 11,
    "soarin": 13,
    "spaceship_earth": 7,
    "rock_n_rollercoaster": 12,
    "toy_story_mania": 14,
    "slinky_dog": 15,
    "alien_saucers": 9,
    "dinosaur": 10,
    "expedition_everest": 11,
    "kilimanjaro_safaris": 9,
    "navi_river": 14,
    "flight_of_passage": 18,
}


def _hour_multiplier(hour: int) -> float:
    if hour <= 8:
        return 0.35
    if hour == 9:
        return 0.70
    if hour == 10:
        return 0.95
    if 11 <= hour <= 15:
        return 1.00
    if hour == 16:
        return 0.92
    if hour == 17:
        return 0.85
    if hour == 18:
        return 0.78
    if hour == 19:
        return 0.70
    if hour == 20:
        return 0.55
    return 0.40


def generate_sample_hourly(
    start: str = "2018-01-01",
    weeks: int = 8,
    seed: int = 42,
) -> pd.DataFrame:
    """Build a small but structured hourly table for demos and CI.

    Shape matches the warehouse hourly grain so Streamlit and the notebook run
    before anyone downloads the full TouringPlans CSVs. Replace by running
    `wdw-ingest-history` then `wdw-build`.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=weeks * 7, freq="D")
    hours = list(range(8, 23))
    specs = attractions()
    park_lookup = parks()
    rows: list[dict] = []
    for spec in specs:
        park = park_lookup[spec["park"]]
        base = MIDDAY_POSTED[spec["key"]]
        bias = POSTED_BIAS[spec["key"]]
        for day in dates:
            is_weekend = int(day.dayofweek >= 5)
            is_holiday = int((day.month, day.day) in {(1, 1), (7, 4), (12, 25)})
            early_entry = int(day.dayofweek in {0, 3})  # Mon/Thu early entry pattern
            for hour in hours:
                noise = float(rng.normal(0, 4))
                weekend_boost = 1.12 if is_weekend else 1.0
                holiday_boost = 1.20 if is_holiday else 1.0
                ee_boost = 1.08 if early_entry and hour <= 10 else 1.0
                posted = max(
                    0.0,
                    base * _hour_multiplier(hour) * weekend_boost * holiday_boost * ee_boost + noise,
                )
                actual = max(0.0, posted - bias + float(rng.normal(0, 2)))
                observed = pd.Timestamp(day) + pd.Timedelta(hours=hour)
                rows.append(
                    {
                        "attraction_key": spec["key"],
                        "attraction_name": spec["name"],
                        "park_key": spec["park"],
                        "park_name": park["name"],
                        "live_entity_id": spec.get("live_entity_id"),
                        "live_name": spec.get("live_name"),
                        "park_date": pd.Timestamp(day),
                        "observed_at": observed,
                        "posted_wait_median": round(posted, 1),
                        "posted_wait_mean": round(posted, 1),
                        "posted_n": int(rng.integers(4, 12)),
                        "actual_wait_median": round(actual, 1),
                        "actual_wait_mean": round(actual, 1),
                        "actual_n": int(rng.integers(1, 5)),
                        "posted_minus_actual": round(posted - actual, 1),
                        "season": "WINTER" if day.month in {1, 2, 12} else "REGULAR",
                        "holiday": is_holiday,
                        "holiday_name": "christmas" if (day.month, day.day) == (12, 25) else None,
                        "ticket_season": "peak" if is_holiday or is_weekend else "regular",
                        "early_entry": early_entry,
                        "is_holiday": is_holiday,
                    }
                )
    frame = add_time_features(pd.DataFrame(rows))
    frame["live_entity_id"] = frame["live_entity_id"].astype("string")
    frame["live_name"] = frame["live_name"].astype("string")
    return frame


def write_committed_sample() -> pd.DataFrame:
    SAMPLE_HOURLY_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    frame = generate_sample_hourly()
    frame.to_parquet(SAMPLE_HOURLY_PARQUET, index=False)
    return frame


if __name__ == "__main__":
    out = write_committed_sample()
    print(f"Wrote {len(out):,} rows to {SAMPLE_HOURLY_PARQUET}")
