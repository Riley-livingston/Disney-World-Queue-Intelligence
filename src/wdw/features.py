"""Time features and hourly aggregates for wait-time modeling."""

from __future__ import annotations

import pandas as pd

US_FEDERALISH_MMDD = {
    (1, 1),  # New Year's Day
    (7, 4),  # Independence Day
    (11, 11),  # Veterans Day
    (12, 25),  # Christmas
    (12, 31),  # New Year's Eve
}


def add_time_features(frame: pd.DataFrame, timestamp_col: str = "observed_at") -> pd.DataFrame:
    out = frame.copy()
    stamps = pd.to_datetime(out[timestamp_col], errors="coerce")
    out["hour"] = stamps.dt.hour
    out["weekday"] = stamps.dt.dayofweek
    out["weekday_name"] = stamps.dt.day_name()
    out["month"] = stamps.dt.month
    out["year"] = stamps.dt.year
    out["weekofyear"] = stamps.dt.isocalendar().week.astype("Int64")
    out["is_weekend"] = (out["weekday"] >= 5).astype(int)
    if "is_holiday" not in out.columns:
        out["is_holiday"] = [
            int((stamp.month, stamp.day) in US_FEDERALISH_MMDD) if pd.notna(stamp) else 0
            for stamp in stamps
        ]
    return out


def hourly_aggregates(waits: pd.DataFrame) -> pd.DataFrame:
    """Collapse noisy 5–15 minute observations to one row per attraction-hour."""
    work = waits.copy()
    work["observed_at"] = pd.to_datetime(work["observed_at"], errors="coerce")
    work = work.dropna(subset=["observed_at"])
    work["hour_start"] = work["observed_at"].dt.floor("h")
    grouped = (
        work.groupby(
            [
                "attraction_key",
                "attraction_name",
                "park_key",
                "park_name",
                "live_entity_id",
                "live_name",
                "park_date",
                "hour_start",
            ],
            dropna=False,
        )
        .agg(
            posted_wait_median=("posted_wait", "median"),
            posted_wait_mean=("posted_wait", "mean"),
            posted_n=("posted_wait", "count"),
            actual_wait_median=("actual_wait", "median"),
            actual_wait_mean=("actual_wait", "mean"),
            actual_n=("actual_wait", "count"),
        )
        .reset_index()
        .rename(columns={"hour_start": "observed_at"})
    )
    grouped["posted_minus_actual"] = grouped["posted_wait_median"] - grouped["actual_wait_median"]
    return grouped
