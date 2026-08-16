"""Typical-day catalog lists every live ride; TouringPlans curves stay historical."""

from __future__ import annotations

import pandas as pd

from wdw.typical import (
    attraction_catalog,
    combine_observations,
    explode_forecasts,
    observations_from_standby,
    typical_day_curve,
)


def test_catalog_includes_live_only_ride() -> None:
    hourly = pd.DataFrame(
        {
            "attraction_key": ["pirates_of_caribbean"],
            "attraction_name": ["Pirates of the Caribbean"],
            "park_name": ["Magic Kingdom Park"],
            "hour": [10],
            "posted_wait_median": [20],
            "actual_wait_median": [12],
        }
    )
    live = pd.DataFrame(
        {
            "entity_id": ["tron-id", "352feb94-e52e-45eb-9c92-e4b44c6b1a9d"],
            "entity_name": ["TRON Lightcycle / Run", "Pirates of the Caribbean"],
            "entity_type": ["ATTRACTION", "ATTRACTION"],
            "park_name": ["Magic Kingdom Park", "Magic Kingdom Park"],
            "standby_wait": [45, 10],
            "fetched_at": ["2026-08-15T18:00:00-04:00", "2026-08-15T18:00:00-04:00"],
            "last_updated": ["2026-08-15T18:00:00-04:00", "2026-08-15T18:00:00-04:00"],
            "forecast": [
                [{"time": "2026-08-15T10:00:00-04:00", "waitTime": 50}],
                [{"time": "2026-08-15T10:00:00-04:00", "waitTime": 15}],
            ],
        }
    )
    catalog = attraction_catalog(hourly, live)
    names = set(catalog["attraction_name"])
    assert "TRON Lightcycle / Run" in names
    assert "Pirates of the Caribbean" in names
    pirates = catalog.loc[catalog["attraction_name"] == "Pirates of the Caribbean"].iloc[0]
    tron = catalog.loc[catalog["attraction_name"] == "TRON Lightcycle / Run"].iloc[0]
    assert bool(pirates["has_touringplans"]) is True
    assert bool(tron["has_touringplans"]) is False


def test_combine_observations_uses_forecast_not_live_standby() -> None:
    hourly = pd.DataFrame(
        {
            "attraction_key": ["pirates_of_caribbean"],
            "attraction_name": ["Pirates of the Caribbean"],
            "park_name": ["Magic Kingdom Park"],
            "hour": [10],
            "posted_wait_median": [20],
            "actual_wait_median": [12],
        }
    )
    live = pd.DataFrame(
        {
            "entity_id": ["tron-id"],
            "entity_name": ["TRON Lightcycle / Run"],
            "entity_type": ["ATTRACTION"],
            "park_name": ["Magic Kingdom Park"],
            "standby_wait": [45],
            "fetched_at": ["2026-08-15T18:00:00-04:00"],
            "forecast": [[{"time": "2026-08-15T10:00:00-04:00", "waitTime": 50}]],
        }
    )
    obs = combine_observations(hourly, live)
    assert set(obs["source"]) <= {"touringplans", "themeparks_forecast"}
    assert "themeparks_live" not in set(obs["source"])
    assert "TRON Lightcycle / Run" in set(obs["attraction_name"])


def test_forecast_from_park_key_without_park_name() -> None:
    raw = pd.DataFrame(
        {
            "entity_id": ["jungle-id"],
            "entity_name": ["Jungle Cruise"],
            "park_key": ["magic_kingdom"],
            "forecast": [
                [
                    {"time": "2026-08-15T10:00:00-04:00", "waitTime": 45},
                    {"time": "2026-08-15T14:00:00-04:00", "waitTime": 35},
                ]
            ],
        }
    )
    forecast = explode_forecasts(raw)
    assert forecast["park_name"].tolist() == ["Magic Kingdom Park", "Magic Kingdom Park"]
    curve = typical_day_curve(forecast, attraction_name="Jungle Cruise")
    assert float(curve.loc[curve["hour"] == 10, "posted_median"].iloc[0]) == 45
    assert float(curve.loc[curve["hour"] == 14, "posted_median"].iloc[0]) == 35
    assert float(curve.loc[curve["hour"] == 6, "posted_median"].iloc[0]) == 0


def test_forecast_posted_percentiles_without_actual() -> None:
    live = pd.DataFrame(
        {
            "entity_id": ["tron-id"],
            "entity_name": ["TRON Lightcycle / Run"],
            "entity_type": ["ATTRACTION"],
            "park_name": ["Magic Kingdom Park"],
            "standby_wait": [45],
            "fetched_at": ["2026-08-15T18:00:00-04:00"],
            "forecast": [
                [
                    {"time": "2026-08-15T10:00:00-04:00", "waitTime": 40},
                    {"time": "2026-08-15T11:00:00-04:00", "waitTime": 55},
                    {"time": "2026-08-15T12:00:00-04:00", "waitTime": 60},
                ]
            ],
        }
    )
    forecast = explode_forecasts(live)
    curve = typical_day_curve(forecast, attraction_name="TRON Lightcycle / Run")
    noon = curve.loc[curve["hour"] == 12].iloc[0]
    assert float(noon["posted_median"]) == 60
    assert float(noon["posted_p25"]) == 60
    assert float(noon["posted_p75"]) == 60
    assert float(curve.loc[curve["hour"] == 6, "posted_median"].iloc[0]) == 0
    assert float(curve["has_actual"].max()) == 0
    assert curve.groupby("hour").size().max() == 1


def test_touringplans_curve_ignores_live_forecast() -> None:
    hourly = pd.DataFrame(
        {
            "attraction_key": ["pirates_of_caribbean"] * 3,
            "attraction_name": ["Pirates of the Caribbean"] * 3,
            "park_name": ["Magic Kingdom Park"] * 3,
            "hour": [10, 11, 12],
            "posted_wait_median": [20.0, 30.0, 40.0],
            "actual_wait_median": [10.0, 18.0, 25.0],
        }
    )
    live = pd.DataFrame(
        {
            "entity_id": ["352feb94-e52e-45eb-9c92-e4b44c6b1a9d"],
            "entity_name": ["Pirates of the Caribbean"],
            "entity_type": ["ATTRACTION"],
            "park_name": ["Magic Kingdom Park"],
            "standby_wait": [5],
            "fetched_at": ["2026-08-15T12:00:00-04:00"],
            "forecast": [[{"time": "2026-08-15T12:00:00-04:00", "waitTime": 5}]],
        }
    )
    obs = pd.concat(
        [
            combine_observations(hourly, live),
            observations_from_standby(live),
        ],
        ignore_index=True,
    )
    curve = typical_day_curve(obs, attraction_name="Pirates of the Caribbean")
    noon = curve.loc[curve["hour"] == 12].iloc[0]
    assert float(noon["posted_median"]) == 40
    assert len(curve) == 21  # one park-day, not a doubled line


def test_all_curves_keep_forecast_only_rides() -> None:
    hourly = pd.DataFrame(
        {
            "attraction_key": ["pirates_of_caribbean"],
            "attraction_name": ["Pirates of the Caribbean"],
            "park_name": ["Magic Kingdom Park"],
            "hour": [12],
            "posted_wait_median": [40.0],
            "actual_wait_median": [25.0],
        }
    )
    live = pd.DataFrame(
        {
            "entity_id": ["jungle-id"],
            "entity_name": ["Jungle Cruise"],
            "entity_type": ["ATTRACTION"],
            "park_name": ["Magic Kingdom Park"],
            "forecast": [[{"time": "2026-08-15T10:00:00-04:00", "waitTime": 45}]],
        }
    )
    obs = pd.concat(
        [combine_observations(hourly), explode_forecasts(live)],
        ignore_index=True,
    )
    curves = typical_day_curve(obs)
    names = set(curves["attraction_name"])
    assert "Pirates of the Caribbean" in names
    assert "Jungle Cruise" in names
    jungle_10 = curves.loc[
        (curves["attraction_name"] == "Jungle Cruise") & (curves["hour"] == 10),
        "posted_median",
    ].iloc[0]
    assert float(jungle_10) == 45
    pirates_12 = curves.loc[
        (curves["attraction_name"] == "Pirates of the Caribbean") & (curves["hour"] == 12),
        "posted_median",
    ].iloc[0]
    assert float(pirates_12) == 40
