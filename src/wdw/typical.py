"""Typical-day posted wait curves for every attraction, not just TouringPlans headliners."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from wdw.config import LIVE_DIR, PROCESSED_DIR, attractions, parks
from wdw.eastern import EASTERN, PARK_DAY_HOURS, hour_et_category, to_eastern

FORECAST_PARQUET = PROCESSED_DIR / "forecasts.parquet"

OBS_COLS = [
    "attraction_key",
    "attraction_name",
    "park_name",
    "hour",
    "month",
    "posted_wait",
    "actual_wait",
    "source",
]


def _display_name(historical_name, live_name) -> str:
    if live_name is None or (isinstance(live_name, float) and pd.isna(live_name)):
        return str(historical_name)
    text = str(live_name).strip()
    if text in {"", "None", "<NA>", "nan"}:
        return str(historical_name)
    return text


def live_name_lookup() -> dict[str, str]:
    return {
        spec["key"]: _display_name(spec["name"], spec.get("live_name"))
        for spec in attractions()
    }


def park_name_lookup() -> dict[str, str]:
    return {key: spec["name"] for key, spec in parks().items()}


def _park_name(rec: dict) -> str | None:
    name = rec.get("park_name")
    if name not in (None, "", "None", "<NA>"):
        if not (isinstance(name, float) and pd.isna(name)):
            return str(name)
    return park_name_lookup().get(rec.get("park_key"))


def observations_from_hourly(hourly: pd.DataFrame) -> pd.DataFrame:
    """One posted (and optional actual) sample per TouringPlans attraction-hour."""
    if hourly is None or hourly.empty:
        return pd.DataFrame(columns=OBS_COLS)
    work = hourly.copy()
    names = live_name_lookup()
    mapped = work["attraction_key"].map(names)
    work["attraction_name"] = mapped.where(mapped.notna(), work["attraction_name"])
    if "hour" not in work.columns:
        work["hour"] = pd.to_datetime(work["observed_at"], errors="coerce").dt.hour
    if "month" in work.columns:
        month = pd.to_numeric(work["month"], errors="coerce")
    elif "observed_at" in work.columns:
        month = pd.to_datetime(work["observed_at"], errors="coerce").dt.month
    else:
        month = pd.Series(pd.NA, index=work.index)
    posted = work["posted_wait_median"] if "posted_wait_median" in work.columns else work.get("posted_wait")
    actual = work["actual_wait_median"] if "actual_wait_median" in work.columns else work.get("actual_wait")
    out = pd.DataFrame(
        {
            "attraction_key": work["attraction_key"].astype(str),
            "attraction_name": work["attraction_name"],
            "park_name": work["park_name"],
            "hour": pd.to_numeric(work["hour"], errors="coerce"),
            "month": month,
            "posted_wait": pd.to_numeric(posted, errors="coerce"),
            "actual_wait": pd.to_numeric(actual, errors="coerce"),
            "source": "touringplans",
        }
    )
    return out.dropna(subset=["hour"])


def observations_from_standby(live: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time posted waits from ThemeParks.wiki snapshots."""
    if live is None or live.empty:
        return pd.DataFrame(columns=OBS_COLS)
    work = live.copy()
    if "entity_type" in work.columns:
        work = work.loc[work["entity_type"] == "ATTRACTION"]
    if work.empty:
        return pd.DataFrame(columns=OBS_COLS)
    stamp = work["last_updated"] if "last_updated" in work.columns else work["fetched_at"]
    hours = []
    for value in stamp:
        ts = to_eastern(value)
        hours.append(ts.hour if ts is not None else pd.NA)
    out = pd.DataFrame(
        {
            "attraction_key": work["entity_id"].astype(str),
            "attraction_name": work["entity_name"],
            "park_name": work["park_name"],
            "hour": hours,
            "month": pd.NA,
            "posted_wait": pd.to_numeric(work.get("standby_wait"), errors="coerce"),
            "actual_wait": pd.NA,
            "source": "themeparks_live",
        }
    )
    return out.dropna(subset=["hour"])


def explode_forecasts(live: pd.DataFrame) -> pd.DataFrame:
    """Disney hourly posted-wait forecast from a ThemeParks.wiki live payload."""
    if live is None or live.empty or "forecast" not in live.columns:
        return pd.DataFrame(columns=OBS_COLS)
    work = live
    if "entity_type" in work.columns:
        work = work.loc[work["entity_type"] == "ATTRACTION"]
    if work.empty:
        return pd.DataFrame(columns=OBS_COLS)
    exploded = work.explode("forecast", ignore_index=True)
    exploded = exploded.loc[exploded["forecast"].map(lambda entry: isinstance(entry, dict))]
    if exploded.empty:
        return pd.DataFrame(columns=OBS_COLS)
    forecast = exploded["forecast"]
    times = pd.to_datetime(forecast.map(lambda entry: entry.get("time")), errors="coerce", utc=True)
    hours = times.dt.tz_convert(EASTERN).dt.hour
    months = times.dt.tz_convert(EASTERN).dt.month
    waits = pd.to_numeric(forecast.map(lambda entry: entry.get("waitTime")), errors="coerce").fillna(0)
    if "park_name" in exploded.columns:
        park_names = exploded["park_name"]
        missing = park_names.isna() | park_names.astype(str).isin(["", "None", "<NA>", "nan"])
    else:
        park_names = pd.Series(pd.NA, index=exploded.index)
        missing = pd.Series(True, index=exploded.index)
    if "park_key" in exploded.columns:
        park_names = park_names.where(~missing, exploded["park_key"].map(park_name_lookup()))
    out = pd.DataFrame(
        {
            "attraction_key": exploded["entity_id"].astype(str),
            "attraction_name": exploded["entity_name"],
            "park_name": park_names,
            "hour": hours,
            "month": months,
            "posted_wait": waits,
            "actual_wait": pd.NA,
            "source": "themeparks_forecast",
        }
    )
    return out.dropna(subset=["hour"]).reset_index(drop=True)


def observations_from_saved_forecasts(path: Path | None = None) -> pd.DataFrame:
    path = path or FORECAST_PARQUET
    if path.exists():
        saved = pd.read_parquet(path)
        if not saved.empty:
            return saved
    frames = []
    if LIVE_DIR.exists():
        for json_path in sorted(LIVE_DIR.glob("forecast_*.json")):
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            raw = pd.DataFrame(payload)
            if raw.empty:
                continue
            frames.append(explode_forecasts(raw))
    if not frames:
        return pd.DataFrame(columns=OBS_COLS)
    return pd.concat(frames, ignore_index=True)


def combine_observations(
    hourly: pd.DataFrame | None = None,
    live: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """TouringPlans history plus ThemeParks posted-wait forecasts for everyone else.

    Current live standby is not mixed in. Rides with TouringPlans rows are later
    filtered to that source only inside `typical_day_curve`.
    """
    parts = [
        observations_from_hourly(hourly if hourly is not None else pd.DataFrame()),
        explode_forecasts(live if live is not None else pd.DataFrame()),
        observations_from_saved_forecasts(),
    ]
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(columns=OBS_COLS)
    out = pd.concat(parts, ignore_index=True)
    out["hour"] = pd.to_numeric(out["hour"], errors="coerce")
    out = out.dropna(subset=["hour", "attraction_name"])
    out["hour"] = out["hour"].astype(int) % 24
    if "month" not in out.columns:
        out["month"] = pd.NA
    out["posted_wait"] = pd.to_numeric(out["posted_wait"], errors="coerce")
    out["actual_wait"] = pd.to_numeric(out["actual_wait"], errors="coerce")
    return out


def attraction_catalog(hourly: pd.DataFrame | None, live: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every live attraction, plus TouringPlans-mapped headliners."""
    rows: list[dict] = []
    if live is not None and not live.empty:
        work = live.copy()
        if "entity_type" in work.columns:
            work = work.loc[work["entity_type"] == "ATTRACTION"]
        for rec in work.drop_duplicates(["entity_name", "park_name"]).to_dict(orient="records"):
            rows.append(
                {
                    "attraction_key": str(rec.get("entity_id")),
                    "attraction_name": rec.get("entity_name"),
                    "park_name": rec.get("park_name"),
                    "has_touringplans": False,
                }
            )
    names = live_name_lookup()
    if hourly is not None and not hourly.empty:
        for rec in hourly.drop_duplicates(["attraction_key"]).to_dict(orient="records"):
            display = names.get(rec["attraction_key"], rec["attraction_name"])
            rows.append(
                {
                    "attraction_key": str(rec["attraction_key"]),
                    "attraction_name": display,
                    "park_name": rec["park_name"],
                    "has_touringplans": True,
                }
            )
    catalog = pd.DataFrame(rows)
    if catalog.empty:
        return catalog
    catalog["has_touringplans"] = catalog.groupby(["attraction_name", "park_name"])[
        "has_touringplans"
    ].transform("any")
    catalog = catalog.dropna(subset=["attraction_name", "park_name"])
    return (
        catalog.drop_duplicates(["attraction_name", "park_name"])
        .sort_values(["park_name", "attraction_name"])
        .reset_index(drop=True)
    )


def empty_typical_day(attraction_name: str, park_name: str, attraction_key: str | None = None) -> pd.DataFrame:
    complete = pd.DataFrame({"hour": PARK_DAY_HOURS})
    complete["attraction_name"] = attraction_name
    complete["park_name"] = park_name
    complete["attraction_key"] = attraction_key or attraction_name
    for col in ("posted_median", "posted_p25", "posted_p75", "actual_median", "forecast_wait"):
        complete[col] = 0.0
    complete["n"] = 0
    complete["has_actual"] = 0
    complete["hour_et"] = hour_et_category(complete["hour"])
    return complete


def has_typical_series(curve: pd.DataFrame) -> bool:
    """True when historical posted waits exist for this attraction."""
    if curve is None or curve.empty or "posted_median" not in curve.columns:
        return False
    posted = pd.to_numeric(curve["posted_median"], errors="coerce").fillna(0)
    if "n" in curve.columns:
        counts = pd.to_numeric(curve["n"], errors="coerce").fillna(0)
        return bool((counts > 0).any() and (posted > 0).any())
    return bool((posted > 0).any())


def has_forecast_series(curve: pd.DataFrame) -> bool:
    if curve is None or curve.empty or "forecast_wait" not in curve.columns:
        return False
    return bool(pd.to_numeric(curve["forecast_wait"], errors="coerce").fillna(0).gt(0).any())


def _filter_history_to_month(history: pd.DataFrame, month: int | None) -> pd.DataFrame:
    """Prefer same calendar month across years; fall back to all months if that month is empty."""
    if history.empty or month is None or "month" not in history.columns:
        return history
    month_num = pd.to_numeric(history["month"], errors="coerce")
    seasonal = history.loc[month_num == int(month)]
    if seasonal.empty:
        return history
    keys = ["attraction_name", "park_name"]
    parts: list[pd.DataFrame] = []
    for key, full in history.groupby(keys, dropna=False):
        part = seasonal.loc[(seasonal["attraction_name"] == key[0]) & (seasonal["park_name"] == key[1])]
        parts.append(part if not part.empty else full)
    return pd.concat(parts, ignore_index=True) if parts else history


def _park_day_frame(meta: pd.Series, posted: pd.DataFrame, forecast: pd.DataFrame) -> pd.DataFrame:
    complete = pd.DataFrame({"hour": PARK_DAY_HOURS})
    if not posted.empty:
        complete = complete.merge(posted, on="hour", how="left")
    if not forecast.empty:
        complete = complete.merge(forecast, on="hour", how="left")
    for col in ("attraction_key", "attraction_name", "park_name"):
        if col not in complete.columns:
            complete[col] = meta.get(col)
        complete[col] = complete[col].fillna(meta.get(col))
    for col in ("posted_median", "posted_p25", "posted_p75", "actual_median"):
        if col not in complete.columns:
            complete[col] = 0.0
        complete[col] = complete[col].fillna(0)
    if "forecast_wait" not in complete.columns:
        complete["forecast_wait"] = pd.NA
    if "n" not in complete.columns:
        complete["n"] = 0
    complete["n"] = complete["n"].fillna(0)
    if "has_actual" not in complete.columns:
        complete["has_actual"] = 0
    complete["has_actual"] = complete["has_actual"].fillna(0)
    complete["hour_et"] = hour_et_category(complete["hour"])
    return complete


def typical_day_curve(
    hourly: pd.DataFrame,
    attraction_key: str | None = None,
    attraction_name: str | None = None,
    live: pd.DataFrame | None = None,
    month: int | None = None,
) -> pd.DataFrame:
    """Historical typical posted wait by hour, plus today's forecast as a separate series.

    Typical posted / 25th–75th / typical actual come only from TouringPlans history
    for the requested calendar month (all years). Rides without that history get
    today's ThemeParks forecast and live standby, not a synthetic typical. Closed /
    missing posted hours plot as 0.
    """
    if hourly is not None and {"posted_wait", "source"}.issubset(hourly.columns):
        work = hourly.copy()
    else:
        work = observations_from_hourly(hourly if hourly is not None else pd.DataFrame())
        if live is not None and not live.empty:
            forecast_rows = explode_forecasts(live)
            if not forecast_rows.empty:
                work = pd.concat([work, forecast_rows], ignore_index=True) if not work.empty else forecast_rows
    if work.empty:
        return pd.DataFrame()
    if attraction_key:
        work = work.loc[work["attraction_key"].astype(str) == str(attraction_key)]
    if attraction_name:
        work = work.loc[work["attraction_name"] == attraction_name]
    if work.empty:
        return pd.DataFrame()
    work["hour"] = pd.to_numeric(work["hour"], errors="coerce")
    work = work.dropna(subset=["hour"])
    work["hour"] = work["hour"].astype(int) % 24
    if "source" in work.columns:
        history = work.loc[work["source"].eq("touringplans")].copy()
        forecast = work.loc[work["source"].eq("themeparks_forecast")].copy()
    else:
        history = work.copy()
        forecast = pd.DataFrame(columns=work.columns)
    history = _filter_history_to_month(history, month)
    if not history.empty:
        posted = pd.to_numeric(history["posted_wait"], errors="coerce").fillna(0).clip(lower=0)
        actual = pd.to_numeric(history["actual_wait"], errors="coerce")
        actual = actual.where(posted > 0, 0)
        history = history.assign(posted_wait=posted, actual_wait=actual)
        if "attraction_key" not in history.columns:
            history["attraction_key"] = history["attraction_name"]
        posted_agg = (
            history.groupby(["attraction_name", "park_name", "hour"], observed=True, dropna=False)
            .agg(
                attraction_key=("attraction_key", "first"),
                posted_median=("posted_wait", "median"),
                posted_p25=("posted_wait", lambda s: s.quantile(0.25)),
                posted_p75=("posted_wait", lambda s: s.quantile(0.75)),
                actual_median=("actual_wait", "median"),
                n=("posted_wait", "size"),
                has_actual=("actual_wait", lambda s: int(s.notna().any() and (s.fillna(0) > 0).any())),
            )
            .reset_index()
        )
    else:
        posted_agg = pd.DataFrame()
    if not forecast.empty:
        if "attraction_key" not in forecast.columns:
            forecast["attraction_key"] = forecast["attraction_name"]
        forecast_agg = (
            forecast.groupby(["attraction_name", "park_name", "hour"], observed=True, dropna=False)
            .agg(
                attraction_key=("attraction_key", "first"),
                forecast_wait=("posted_wait", "median"),
            )
            .reset_index()
        )
    else:
        forecast_agg = pd.DataFrame()
    keys = ["attraction_name", "park_name"]
    combos: list[tuple] = []
    for frame in (posted_agg, forecast_agg):
        if frame.empty:
            continue
        combos.extend(list(frame[keys].drop_duplicates().itertuples(index=False, name=None)))
    combos = list(dict.fromkeys(combos))
    if not combos:
        return pd.DataFrame()
    filled: list[pd.DataFrame] = []
    for name, park in combos:
        posted_slice = (
            posted_agg.loc[(posted_agg["attraction_name"] == name) & (posted_agg["park_name"] == park)].drop(
                columns=keys, errors="ignore"
            )
            if not posted_agg.empty
            else pd.DataFrame()
        )
        forecast_slice = (
            forecast_agg.loc[(forecast_agg["attraction_name"] == name) & (forecast_agg["park_name"] == park)][
                ["hour", "forecast_wait"]
            ]
            if not forecast_agg.empty
            else pd.DataFrame()
        )
        key_val = name
        for frame in (posted_agg, forecast_agg):
            if frame.empty:
                continue
            hit = frame.loc[(frame["attraction_name"] == name) & (frame["park_name"] == park)]
            if not hit.empty and "attraction_key" in hit.columns:
                key_val = hit["attraction_key"].iloc[0]
                break
        meta = pd.Series({"attraction_name": name, "park_name": park, "attraction_key": key_val})
        filled.append(_park_day_frame(meta, posted_slice, forecast_slice))
    out = pd.concat(filled, ignore_index=True)
    return out.sort_values(["attraction_name", "hour_et"]).reset_index(drop=True)
