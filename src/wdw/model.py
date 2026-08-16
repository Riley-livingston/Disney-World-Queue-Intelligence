"""Historical expected wait and posted-vs-actual summaries."""

from __future__ import annotations

import pandas as pd

from wdw.warehouse import load_hourly

TARGET = "posted_wait_median"


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["observed_at"] = pd.to_datetime(work["observed_at"], errors="coerce")
    work = work.dropna(subset=[TARGET, "observed_at"])
    work = work.loc[work[TARGET] >= 0]
    for col in ("is_holiday", "early_entry", "is_weekend", "hour", "weekday", "month"):
        if col not in work.columns:
            work[col] = 0
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0).astype(int)
    work["attraction_key"] = work["attraction_key"].astype(str)
    if "park_key" in work.columns:
        work["park_key"] = work["park_key"].astype(str)
    return work.sort_values("observed_at").reset_index(drop=True)


def expected_wait(live_rows: pd.DataFrame, hourly: pd.DataFrame | None = None) -> pd.DataFrame:
    """Score mapped live attractions against the historical hour/weekday median."""
    history = _prepare(hourly if hourly is not None else load_hourly())
    now = pd.Timestamp.now(tz="America/New_York")
    mapped = live_rows.dropna(subset=["entity_id"]).copy()
    key_by_entity = (
        history.dropna(subset=["live_entity_id"])
        .drop_duplicates("live_entity_id")
        .set_index("live_entity_id")["attraction_key"]
        .to_dict()
    )
    name_by_entity = (
        history.dropna(subset=["live_entity_id"])
        .drop_duplicates("live_entity_id")
        .set_index("live_entity_id")["attraction_name"]
        .to_dict()
    )
    mapped["attraction_key"] = mapped["entity_id"].map(key_by_entity)
    mapped = mapped.dropna(subset=["attraction_key"])
    if mapped.empty:
        return mapped
    mapped["attraction_name"] = mapped["entity_id"].map(name_by_entity)
    mapped["hour"] = now.hour
    mapped["weekday"] = now.dayofweek
    lookup = (
        history.groupby(["attraction_key", "hour", "weekday"])[TARGET]
        .median()
        .rename("expected_wait")
    )
    mapped = mapped.merge(lookup, on=["attraction_key", "hour", "weekday"], how="left")
    attraction_median = history.groupby("attraction_key")[TARGET].median()
    mapped["expected_wait"] = mapped["expected_wait"].fillna(mapped["attraction_key"].map(attraction_median))
    mapped["delta_vs_expected"] = mapped["standby_wait"] - mapped["expected_wait"]
    return mapped


def posted_vs_actual(hourly: pd.DataFrame) -> pd.DataFrame:
    work = hourly.dropna(subset=["posted_wait_median", "actual_wait_median"]).copy()
    work = work.loc[(work["posted_n"] > 0) & (work["actual_n"] > 0)]
    summary = (
        work.groupby(["attraction_key", "attraction_name", "park_name"], observed=True)
        .agg(
            posted_median=("posted_wait_median", "median"),
            actual_median=("actual_wait_median", "median"),
            bias_median=("posted_minus_actual", "median"),
            bias_mean=("posted_minus_actual", "mean"),
            n=("posted_minus_actual", "size"),
        )
        .reset_index()
        .sort_values("bias_mean", ascending=False)
    )
    return summary
