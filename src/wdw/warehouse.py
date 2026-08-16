"""Load TouringPlans CSVs (and live snapshots) into parquet + DuckDB."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from wdw.config import (
    CLOSED_POSTED_WAIT,
    DUCKDB_PATH,
    HOURLY_PARQUET,
    LIVE_PARQUET,
    METADATA_FILE,
    PARK_DAYS_PARQUET,
    SAMPLE_HOURLY_PARQUET,
    TOURINGPLANS_DIR,
    attractions,
    ensure_data_dirs,
    parks,
)
from wdw.features import add_time_features, hourly_aggregates


def _parse_park_date(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    if parsed.isna().mean() > 0.5:
        parsed = pd.to_datetime(series, errors="coerce")
    return parsed.dt.normalize()


def _column(frame: pd.DataFrame, *names: str) -> pd.Series | None:
    lookup = {str(col).strip().upper(): col for col in frame.columns}
    for name in names:
        matched = lookup.get(name.strip().upper())
        if matched is not None:
            return frame[matched]
    return None


def load_metadata(path: Path | None = None) -> pd.DataFrame:
    path = path or (TOURINGPLANS_DIR / METADATA_FILE)
    if not path.exists():
        return pd.DataFrame()
    raw = pd.read_csv(path)
    date_col = _column(raw, "DATE")
    if date_col is None:
        return pd.DataFrame()
    frame = pd.DataFrame()
    frame["park_date"] = _parse_park_date(date_col)
    season = _column(raw, "SEASON", "WDWSEASON")
    frame["season"] = season if season is not None else pd.NA
    holiday = _column(raw, "HOLIDAY")
    frame["holiday"] = pd.to_numeric(holiday, errors="coerce").fillna(0).astype(int) if holiday is not None else 0
    holiday_name = _column(raw, "HOLIDAYN")
    frame["holiday_name"] = holiday_name if holiday_name is not None else pd.NA
    ticket = _column(raw, "WDW_TICKET_SEASON", "WDWTICKETSEASON")
    frame["ticket_season"] = (
        ticket.astype(str).str.lower().replace({"nan": pd.NA}) if ticket is not None else pd.NA
    )
    mean_temp = _column(raw, "WDWMEANTEMP", "WEATHER_WDWHIGH")
    frame["wdw_mean_temp"] = pd.to_numeric(mean_temp, errors="coerce") if mean_temp is not None else pd.NA
    precip = _column(raw, "WEATHER_WDWPRECIP")
    frame["wdw_precip"] = pd.to_numeric(precip, errors="coerce") if precip is not None else pd.NA
    for park, prefix in (("mk", "MK"), ("ep", "EP"), ("hs", "HS"), ("ak", "AK")):
        emh_morn = _column(raw, f"{prefix}EMHMORN")
        emh_eve = _column(raw, f"{prefix}EMHEVE")
        hours = _column(raw, f"{prefix}HOURS")
        frame[f"{park}_emh_morn"] = (
            pd.to_numeric(emh_morn, errors="coerce").fillna(0).astype(int) if emh_morn is not None else 0
        )
        frame[f"{park}_emh_eve"] = (
            pd.to_numeric(emh_eve, errors="coerce").fillna(0).astype(int) if emh_eve is not None else 0
        )
        frame[f"{park}_hours"] = pd.to_numeric(hours, errors="coerce") if hours is not None else pd.NA
    return frame.dropna(subset=["park_date"]).drop_duplicates(subset=["park_date"])


def load_attraction_csv(spec: dict, path: Path | None = None) -> pd.DataFrame:
    path = path or (TOURINGPLANS_DIR / spec["file"])
    if not path.exists():
        return pd.DataFrame()
    raw = pd.read_csv(path)
    raw.columns = [c.strip() for c in raw.columns]
    rename = {}
    for candidate in ("date", "DATE", "park_date"):
        if candidate in raw.columns:
            rename[candidate] = "park_date"
            break
    for candidate in ("datetime", "DATETIME", "wait_datetime"):
        if candidate in raw.columns:
            rename[candidate] = "observed_at"
            break
    for candidate in ("SPOSTMIN", "wait_minutes_posted"):
        if candidate in raw.columns:
            rename[candidate] = "posted_wait"
            break
    for candidate in ("SACTMIN", "wait_minutes_actual"):
        if candidate in raw.columns:
            rename[candidate] = "actual_wait"
            break
    frame = raw.rename(columns=rename)
    if "park_date" not in frame.columns:
        return pd.DataFrame()
    frame["park_date"] = _parse_park_date(frame["park_date"])
    if "observed_at" in frame.columns:
        frame["observed_at"] = pd.to_datetime(frame["observed_at"], errors="coerce")
    else:
        frame["observed_at"] = frame["park_date"]
    for col in ("posted_wait", "actual_wait"):
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        else:
            frame[col] = pd.NA
    frame.loc[frame["posted_wait"] == CLOSED_POSTED_WAIT, "posted_wait"] = pd.NA
    park_spec = parks()[spec["park"]]
    frame["attraction_key"] = spec["key"]
    frame["attraction_name"] = spec["name"]
    frame["park_key"] = spec["park"]
    frame["park_name"] = park_spec["name"]
    frame["live_entity_id"] = spec.get("live_entity_id")
    frame["live_name"] = spec.get("live_name")
    return frame[
        [
            "attraction_key",
            "attraction_name",
            "park_key",
            "park_name",
            "live_entity_id",
            "live_name",
            "park_date",
            "observed_at",
            "posted_wait",
            "actual_wait",
        ]
    ]


def load_all_waits() -> pd.DataFrame:
    frames = [load_attraction_csv(spec) for spec in attractions()]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def build_hourly(waits: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    if waits.empty:
        return pd.DataFrame()
    hourly = hourly_aggregates(waits)
    if metadata.empty:
        hourly = add_time_features(hourly)
        hourly["season"] = pd.NA
        hourly["is_holiday"] = 0
        hourly["ticket_season"] = pd.NA
        hourly["early_entry"] = 0
        return hourly
    merged = hourly.merge(metadata, on="park_date", how="left")
    merged = add_time_features(merged)
    emh_map = {
        "magic_kingdom": "mk_emh_morn",
        "epcot": "ep_emh_morn",
        "hollywood_studios": "hs_emh_morn",
        "animal_kingdom": "ak_emh_morn",
    }
    merged["early_entry"] = 0
    for park_key, col in emh_map.items():
        if col in merged.columns:
            merged.loc[merged["park_key"] == park_key, "early_entry"] = (
                pd.to_numeric(merged.loc[merged["park_key"] == park_key, col], errors="coerce")
                .fillna(0)
                .astype(int)
            )
    merged["is_holiday"] = pd.to_numeric(merged.get("holiday"), errors="coerce").fillna(0).astype(int)
    return merged


def write_sample(hourly: pd.DataFrame, rows: int = 12000) -> Path:
    SAMPLE_HOURLY_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    if hourly.empty:
        return SAMPLE_HOURLY_PARQUET
    sample = hourly.dropna(subset=["posted_wait_median"]).copy()
    if len(sample) > rows:
        pieces = []
        grouped = sample.groupby(["attraction_key", "hour"], group_keys=False)
        per_group = max(8, rows // max(grouped.ngroups, 1))
        for _, group in grouped:
            take = min(len(group), per_group)
            pieces.append(group.sample(take, random_state=42))
        sample = pd.concat(pieces, ignore_index=True)
        if len(sample) > rows:
            sample = sample.sample(rows, random_state=42)
    sample.to_parquet(SAMPLE_HOURLY_PARQUET, index=False)
    return SAMPLE_HOURLY_PARQUET


def write_duckdb(hourly: pd.DataFrame, park_days: pd.DataFrame, live: pd.DataFrame | None) -> Path:
    ensure_data_dirs()
    if DUCKDB_PATH.exists():
        DUCKDB_PATH.unlink()
    con = duckdb.connect(str(DUCKDB_PATH))
    con.register("hourly_df", hourly)
    con.execute("CREATE TABLE hourly AS SELECT * FROM hourly_df")
    if not park_days.empty:
        con.register("park_days_df", park_days)
        con.execute("CREATE TABLE park_days AS SELECT * FROM park_days_df")
    if live is not None and not live.empty:
        con.register("live_df", live)
        con.execute("CREATE TABLE live_snapshots AS SELECT * FROM live_df")
    con.close()
    return DUCKDB_PATH


def build_warehouse() -> dict[str, Path]:
    ensure_data_dirs()
    waits = load_all_waits()
    metadata = load_metadata()
    hourly = build_hourly(waits, metadata)
    if hourly.empty:
        raise FileNotFoundError(
            f"No TouringPlans CSVs found in {TOURINGPLANS_DIR}. "
            "Run `wdw-ingest-history` first."
        )
    hourly.to_parquet(HOURLY_PARQUET, index=False)
    if not metadata.empty:
        metadata.to_parquet(PARK_DAYS_PARQUET, index=False)
    live = pd.read_parquet(LIVE_PARQUET) if LIVE_PARQUET.exists() else pd.DataFrame()
    write_sample(hourly)
    write_duckdb(hourly, metadata, live if not live.empty else None)
    return {
        "hourly": HOURLY_PARQUET,
        "park_days": PARK_DAYS_PARQUET,
        "sample": SAMPLE_HOURLY_PARQUET,
        "duckdb": DUCKDB_PATH,
    }


def load_hourly(prefer_full: bool = True) -> pd.DataFrame:
    """Load the full hourly table, falling back to the committed sample."""
    if prefer_full and HOURLY_PARQUET.exists():
        frame = pd.read_parquet(HOURLY_PARQUET)
    elif SAMPLE_HOURLY_PARQUET.exists():
        frame = pd.read_parquet(SAMPLE_HOURLY_PARQUET)
    elif HOURLY_PARQUET.exists():
        frame = pd.read_parquet(HOURLY_PARQUET)
    else:
        from wdw.sample_data import write_committed_sample

        frame = write_committed_sample()
    allowed = {spec["key"] for spec in attractions()}
    if "attraction_key" in frame.columns:
        frame = frame.loc[frame["attraction_key"].isin(allowed)].copy()
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the WDW DuckDB warehouse.")
    parser.parse_args(argv)
    written = build_warehouse()
    for label, path in written.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
