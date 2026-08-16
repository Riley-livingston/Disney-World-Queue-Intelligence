"""Live weather for the Walt Disney World resort area (Lake Buena Vista, FL).

Forecast is Open-Meteo. Alerts and radar are National Weather Service (Melbourne, KMLB).
This is not a Disney weather product.
"""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from wdw.config import MAX_RETRIES, TIMEZONE
from wdw.eastern import hour_label

WEATHER_CREDIT = "Forecast: Open-Meteo. Radar: RainViewer. Alerts: National Weather Service."
WDW_LATITUDE = 28.3852
WDW_LONGITUDE = -81.5639
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NWS_ALERTS_URL = f"https://api.weather.gov/alerts/active?point={WDW_LATITUDE},{WDW_LONGITUDE}"
NWS_USER_AGENT = "(Disney World Queue Intelligence portfolio; https://github.com/Riley-livingston/Disney-World-Queue-Intelligence)"
RAINVIEWER_MAPS_URL = "https://api.rainviewer.com/public/weather-maps.json"
PARK_POINTS = [
    {"name": "Magic Kingdom", "lat": 28.4177, "lon": -81.5812},
    {"name": "EPCOT", "lat": 28.3747, "lon": -81.5494},
    {"name": "Hollywood Studios", "lat": 28.3578, "lon": -81.5583},
    {"name": "Animal Kingdom", "lat": 28.3587, "lon": -81.5916},
]

# WMO weather interpretation codes used by Open-Meteo.
WEATHER_CODES = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}

THUNDERSTORM_CODES = {95, 96, 99}


class WeatherError(RuntimeError):
    """Raised when a weather feed cannot be reached."""


def weather_label(code: int | None) -> str:
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return "Unknown"
    return WEATHER_CODES.get(int(code), f"Code {int(code)}")


def is_thunderstorm(code: int | None) -> bool:
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return False
    return int(code) in THUNDERSTORM_CODES


def ops_implication(current: dict[str, Any], hourly: pd.DataFrame) -> str:
    code = current.get("weather_code")
    precip_now = current.get("precipitation") or 0
    next_precip = 0.0
    if hourly is not None and not hourly.empty and "precip_chance" in hourly.columns:
        next_precip = float(pd.to_numeric(hourly["precip_chance"].head(6), errors="coerce").max() or 0)
    if is_thunderstorm(code) or next_precip >= 70:
        return (
            "Storm risk this cycle. Outdoor queues, shows, and boats may suspend under a 30/30 lightning hold. "
            "Watch NWS alerts and stage indoor capacity."
        )
    if precip_now > 0 or next_precip >= 40:
        return "Rain likely. Expect slower outdoor walkways and higher indoor attraction demand."
    if (current.get("wind_gusts") or 0) >= 30:
        return "Gusty winds. Check outdoor sets, parade/float, and crane restrictions."
    return "No weather hold indicated from this forecast. Keep watching radar through the afternoon."


def parse_open_meteo(payload: dict[str, Any]) -> dict[str, Any]:
    current = payload.get("current") or {}
    hourly = payload.get("hourly") or {}
    daily = payload.get("daily") or {}
    times = hourly.get("time") or []
    hours = pd.DataFrame(
        {
            "time": pd.to_datetime(times),
            "temp_f": hourly.get("temperature_2m"),
            "precip_chance": hourly.get("precipitation_probability"),
            "precip_in": hourly.get("precipitation"),
            "weather_code": hourly.get("weather_code"),
            "wind_mph": hourly.get("wind_speed_10m"),
        }
    )
    if not hours.empty:
        hours["hour"] = hours["time"].dt.hour
        hours["hour_et"] = [hour_label(int(h)) for h in hours["hour"]]
    current_out = {
        "temp_f": current.get("temperature_2m"),
        "feels_like_f": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "precip_in": current.get("precipitation"),
        "weather_code": current.get("weather_code"),
        "condition": weather_label(current.get("weather_code")),
        "wind_mph": current.get("wind_speed_10m"),
        "wind_gusts": current.get("wind_gusts_10m"),
        "cloud_cover": current.get("cloud_cover"),
        "as_of": current.get("time"),
    }
    highs = daily.get("temperature_2m_max") or [None]
    lows = daily.get("temperature_2m_min") or [None]
    rain_chance = daily.get("precipitation_probability_max") or [None]
    return {
        "current": current_out,
        "hourly": hours,
        "today_high_f": highs[0] if highs else None,
        "today_low_f": lows[0] if lows else None,
        "today_precip_chance": rain_chance[0] if rain_chance else None,
        "thunderstorm": is_thunderstorm(current.get("weather_code")),
    }


def parse_nws_alerts(payload: dict[str, Any]) -> list[dict[str, str]]:
    alerts = []
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        headline = props.get("headline") or props.get("event") or "NWS alert"
        alerts.append(
            {
                "event": props.get("event") or "Alert",
                "severity": props.get("severity") or "",
                "headline": headline,
                "instruction": (props.get("instruction") or "")[:400],
            }
        )
    return alerts


def fetch_open_meteo(client: httpx.Client | None = None) -> dict[str, Any]:
    params = {
        "latitude": WDW_LATITUDE,
        "longitude": WDW_LONGITUDE,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_gusts_10m,cloud_cover",
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": TIMEZONE,
        "forecast_days": 2,
    }
    http = client or httpx.Client(timeout=20.0)
    owns = client is None
    last_error: Exception | None = None
    try:
        for attempt in range(MAX_RETRIES):
            try:
                response = http.get(OPEN_METEO_URL, params=params)
                response.raise_for_status()
                return parse_open_meteo(response.json())
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
        raise WeatherError("Open-Meteo forecast failed") from last_error
    finally:
        if owns:
            http.close()


def fetch_nws_alerts(client: httpx.Client | None = None) -> list[dict[str, str]]:
    http = client or httpx.Client(timeout=20.0, headers={"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"})
    owns = client is None
    try:
        response = http.get(NWS_ALERTS_URL)
        response.raise_for_status()
        return parse_nws_alerts(response.json())
    except (httpx.HTTPError, ValueError):
        return []
    finally:
        if owns:
            http.close()


def parse_rainviewer_tile_url(payload: dict[str, Any]) -> str | None:
    """Latest observed radar tiles, transparent where there is no rain."""
    host = str(payload.get("host") or "https://tilecache.rainviewer.com").rstrip("/")
    radar = payload.get("radar") or {}
    past = radar.get("past") or []
    frame = past[-1] if past else None
    if not frame:
        nowcast = radar.get("nowcast") or []
        frame = nowcast[-1] if nowcast else None
    if not frame or not frame.get("path"):
        return None
    path = str(frame["path"])
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{host}{path}/256/{{z}}/{{x}}/{{y}}/6/1_1.png"


def fetch_radar_tile_url(client: httpx.Client | None = None) -> str | None:
    http = client or httpx.Client(timeout=15.0)
    owns = client is None
    try:
        response = http.get(RAINVIEWER_MAPS_URL)
        response.raise_for_status()
        return parse_rainviewer_tile_url(response.json())
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    finally:
        if owns:
            http.close()


def fetch_wdw_weather() -> dict[str, Any]:
    forecast = fetch_open_meteo()
    forecast["alerts"] = fetch_nws_alerts()
    forecast["implication"] = ops_implication(forecast["current"], forecast["hourly"])
    forecast["radar_tiles"] = fetch_radar_tile_url()
    return forecast
