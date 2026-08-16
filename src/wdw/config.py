"""Paths, park IDs, and API settings for Disney World Queue Intelligence."""

from __future__ import annotations

from pathlib import Path

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
TOURINGPLANS_DIR = RAW_DIR / "touringplans"
LIVE_DIR = RAW_DIR / "themeparks"
PROCESSED_DIR = DATA_DIR / "processed"
SAMPLE_DIR = DATA_DIR / "sample"

DUCKDB_PATH = PROCESSED_DIR / "wdw.duckdb"
HOURLY_PARQUET = PROCESSED_DIR / "hourly.parquet"
PARK_DAYS_PARQUET = PROCESSED_DIR / "park_days.parquet"
LIVE_PARQUET = PROCESSED_DIR / "live_snapshots.parquet"
SAMPLE_HOURLY_PARQUET = SAMPLE_DIR / "hourly_sample.parquet"
SAMPLE_LIVE_PARQUET = SAMPLE_DIR / "live_sample.parquet"
FORECAST_PARQUET = PROCESSED_DIR / "forecasts.parquet"

ATTRACTION_MAP_PATH = PACKAGE_DIR / "attraction_map.yml"

THEMEPARKS_BASE_URL = "https://api.themeparks.wiki/v1"
WDW_DESTINATION_ID = "e957da41-3552-4cf6-b636-5babc5cbc4e5"
TIMEZONE = "America/New_York"

# Lake Buena Vista / Walt Disney World resort area (not a Disney weather product).
WDW_LATITUDE = 28.3852
WDW_LONGITUDE = -81.5639
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NWS_ALERTS_URL = f"https://api.weather.gov/alerts/active?point={WDW_LATITUDE},{WDW_LONGITUDE}"
NWS_USER_AGENT = "(Disney World Queue Intelligence portfolio; https://github.com/Riley-livingston/Disney-World-Queue-Intelligence)"
# Melbourne, FL WSR-88D covers the four Orlando theme parks.
NWS_RADAR_STATION = "KMLB"
NWS_RADAR_LOOP = "https://radar.weather.gov/ridge/standard/KMLB_loop.gif"
NWS_RADAR_PAGE = "https://radar.weather.gov/station/KMLB/standard"

# ThemeParks.wiki caches live data for a few minutes. Hitting faster returns stale data
# and burns the 300 req / 5 min budget.
LIVE_CACHE_SECONDS = 5 * 60
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_RETRIES = 3

TOURINGPLANS_MIRROR_BASE = (
    "https://raw.githubusercontent.com/LucyMcGowan/touringplans/master/data-raw"
)
TOURINGPLANS_OFFICIAL_URL = (
    "https://touringplans.com/walt-disney-world/crowd-calendar#DataSets"
)
METADATA_FILE = "touringplans_metadata.csv"

# Posted wait of -999 in TouringPlans files means the attraction was closed.
CLOSED_POSTED_WAIT = -999


def load_attraction_map() -> dict:
    with ATTRACTION_MAP_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def parks() -> dict[str, dict]:
    return load_attraction_map()["parks"]


def attractions() -> list[dict]:
    return load_attraction_map()["attractions"]


def park_entity_ids() -> dict[str, str]:
    return {key: spec["entity_id"] for key, spec in parks().items()}


def ensure_data_dirs() -> None:
    for path in (TOURINGPLANS_DIR, LIVE_DIR, PROCESSED_DIR, SAMPLE_DIR):
        path.mkdir(parents=True, exist_ok=True)
