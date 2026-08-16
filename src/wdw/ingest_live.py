"""Snapshot live Walt Disney World waits from ThemeParks.wiki into parquet."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from wdw.config import LIVE_DIR, LIVE_PARQUET, PROCESSED_DIR, SAMPLE_LIVE_PARQUET, ensure_data_dirs
from wdw.themeparks import ThemeParksClient, flatten_live, flatten_schedules
from wdw.typical import explode_forecasts

FORECAST_PARQUET = PROCESSED_DIR / "forecasts.parquet"


def snapshot_live(client: ThemeParksClient | None = None) -> pd.DataFrame:
    client = client or ThemeParksClient()
    ensure_data_dirs()
    fetched_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    live = client.wdw_live()
    schedules = client.wdw_schedules()

    raw_path = LIVE_DIR / f"live_{fetched_at}.json"
    raw_path.write_text(
        json.dumps({"live": live, "schedules": schedules}, indent=2),
        encoding="utf-8",
    )

    live_rows = flatten_live(live)
    live_df = pd.DataFrame(live_rows)
    forecast_df = explode_forecasts(live_df)
    if not forecast_df.empty:
        if FORECAST_PARQUET.exists():
            forecast_df = pd.concat(
                [pd.read_parquet(FORECAST_PARQUET), forecast_df], ignore_index=True
            )
        FORECAST_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        forecast_df.to_parquet(FORECAST_PARQUET, index=False)
    if "forecast" in live_df.columns:
        forecast_path = LIVE_DIR / f"forecast_{fetched_at}.json"
        forecast_path.write_text(
            json.dumps(
                live_df[["entity_id", "entity_name", "park_key", "park_name", "forecast"]].to_dict(orient="records"),
                indent=2,
            ),
            encoding="utf-8",
        )
        live_df = live_df.drop(columns=["forecast"])

    schedule_df = pd.DataFrame(flatten_schedules(schedules))
    schedule_path = PROCESSED_DIR / "schedules.parquet"
    if not schedule_df.empty:
        schedule_df.to_parquet(schedule_path, index=False)

    if LIVE_PARQUET.exists():
        existing = pd.read_parquet(LIVE_PARQUET)
        combined = pd.concat([existing, live_df], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["fetched_at", "entity_id"], keep="last"
        )
    else:
        combined = live_df
    combined.to_parquet(LIVE_PARQUET, index=False)
    SAMPLE_LIVE_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    live_df.to_parquet(SAMPLE_LIVE_PARQUET, index=False)
    return live_df


def latest_live_frame() -> pd.DataFrame | None:
    for path in (LIVE_PARQUET, SAMPLE_LIVE_PARQUET):
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty:
            continue
        latest = df["fetched_at"].max()
        return df.loc[df["fetched_at"] == latest].copy()
    return None


def latest_raw_payload() -> dict | None:
    files = sorted(LIVE_DIR.glob("live_*.json"))
    if not files:
        return None
    return json.loads(Path(files[-1]).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot live WDW wait times.")
    parser.parse_args(argv)
    frame = snapshot_live()
    print(f"Wrote {len(frame)} live rows to {LIVE_PARQUET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
