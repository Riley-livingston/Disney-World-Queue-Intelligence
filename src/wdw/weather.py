"""Live weather for the Walt Disney World resort area (Lake Buena Vista, FL).

Forecast is Open-Meteo. Radar is RainViewer over the four parks.
Alerts are NWS products that cover Orange and Osceola counties.
This is not a Disney weather product.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from wdw.config import MAX_RETRIES, TIMEZONE
from wdw.eastern import format_clock, hour_label

WEATHER_CREDIT = "Forecast: Open-Meteo. Radar: RainViewer and NCEP HRRR. Alerts: NWS for Lake Buena Vista."
HRRR_META_URL = "https://mesonet.agron.iastate.edu/data/gis/images/4326/hrrr/refd_0000.json"
HRRR_TILE_HOST = "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0"
HRRR_FORECAST_HOURS = 2
HRRR_STEP_MINUTES = 15
HRRR_MAX_MINUTE = 18 * 60
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


def nws_event_kind(event: str) -> str:
    """Map an NWS product name to alert, watch, or clear for a park-hold brief."""
    name = (event or "").lower()
    if not name:
        return "clear"
    if any(token in name for token in ("heat", "dense fog", "frost", "freeze", "air quality", "rip current")):
        return "clear"
    if any(
        token in name
        for token in (
            "tornado warning",
            "severe thunderstorm warning",
            "extreme wind warning",
        )
    ):
        return "alert"
    if "warning" in name and any(token in name for token in ("thunderstorm", "tornado", "flood")):
        return "alert"
    if "special weather statement" in name:
        return "watch"
    if "watch" in name and any(token in name for token in ("thunderstorm", "tornado", "flood")):
        return "watch"
    return "watch"


def nws_hold_status(alerts: list[dict] | None) -> str:
    kinds = [nws_event_kind(str(alert.get("event") or "")) for alert in (alerts or [])]
    if "alert" in kinds:
        return "alert"
    if "watch" in kinds:
        return "watch"
    return "clear"


def _nws_event_names(alerts: list[dict]) -> str:
    names = []
    for alert in alerts or []:
        event = str(alert.get("event") or "").strip()
        if event and event not in names:
            names.append(event)
    return ", ".join(names)


def ops_implication(current: dict[str, Any], hourly: pd.DataFrame, alerts: list[dict] | None = None) -> str:
    nws = nws_hold_status(alerts)
    events = _nws_event_names(alerts or [])
    if nws == "alert":
        return (
            f"NWS {events} for the resort area. Outdoor queues, shows, and boats may suspend under a 30/30 lightning hold. "
            "This is not an official Disney hold. Watch radar."
        )
    if nws == "watch":
        return (
            f"NWS {events} for the area. That is a heads-up, not automatically a park lightning hold. "
            "Watch radar through this cycle."
        )
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


RESORT_AREA_TOKENS = ("orange", "osceola", "lake buena vista", "bay lake", "orlando")


def covers_wdw_resort(area_desc: str | None) -> bool:
    """Keep alerts that name the park counties. Drop Brevard/Melbourne-only products."""
    text = (area_desc or "").lower()
    if not text:
        return True
    return any(token in text for token in RESORT_AREA_TOKENS)


def headline_for_resort(headline: str) -> str:
    """NWS Melbourne is the forecast office for Orlando. Do not read that as Melbourne Beach."""
    text = headline or ""
    text = text.replace("by NWS Melbourne FL", "for the Lake Buena Vista area")
    text = text.replace("NWS Melbourne FL", "NWS (Lake Buena Vista area)")
    return text


def parse_nws_alerts(payload: dict[str, Any]) -> list[dict[str, str]]:
    alerts = []
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        area = props.get("areaDesc") or ""
        if not covers_wdw_resort(area):
            continue
        event = props.get("event") or "Alert"
        headline = headline_for_resort(props.get("headline") or event)
        alerts.append(
            {
                "event": event,
                "severity": props.get("severity") or "",
                "headline": headline,
                "area": area,
                "instruction": (props.get("instruction") or "")[:400],
                "kind": nws_event_kind(str(event)),
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


def _rainviewer_host(payload: dict[str, Any]) -> str:
    host = str(payload.get("host") or "https://tilecache.rainviewer.com").rstrip("/")
    if host.startswith("//"):
        host = f"https:{host}"
    elif not host.startswith("http"):
        host = f"https://{host}"
    return host


def _rainviewer_tile_template(host: str, path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    # Color 2 is Universal Blue, the free RainViewer scheme. Native tiles stop at zoom 7.
    # 512px tiles are drawn at 256 CSS pixels for a sharper overlay.
    return f"{host}{path}/512/{{z}}/{{x}}/{{y}}/2/1_1.png"


def _rainviewer_unix(frame: dict[str, Any]) -> int | None:
    raw = frame.get("time")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    tail = str(frame.get("path") or "").rstrip("/").split("/")[-1]
    if tail.isdigit() and len(tail) >= 10:
        return int(tail)
    return None


def _radar_time_et(unix: int | None) -> str:
    if unix is None:
        return ""
    return format_clock(pd.Timestamp(unix, unit="s", tz="UTC"))


def parse_rainviewer_frames(payload: dict[str, Any], max_frames: int | None = None) -> list[dict[str, Any]]:
    """Observed radar frames, oldest to newest, with Eastern clock labels."""
    host = _rainviewer_host(payload)
    radar = payload.get("radar") or {}
    past = [frame for frame in (radar.get("past") or []) if frame.get("path")]
    nowcast = [frame for frame in (radar.get("nowcast") or []) if frame.get("path")]
    source = past or nowcast
    if not source:
        return []
    selected = source if max_frames is None else source[-max_frames:]
    frames = []
    for frame in selected:
        unix = _rainviewer_unix(frame)
        frames.append(
            {
                "url": _rainviewer_tile_template(host, str(frame["path"])),
                "time_et": _radar_time_et(unix),
                "kind": "observed",
                "unix": unix,
            }
        )
    return frames


def _hrrr_init_stamp(model_init_utc: str) -> str:
    ts = pd.to_datetime(model_init_utc, utc=True, errors="coerce")
    if pd.isna(ts):
        return ""
    return ts.strftime("%Y%m%d%H%M")


def parse_hrrr_forecast_frames(
    meta: dict[str, Any],
    now: datetime | None = None,
    horizon_hours: int = HRRR_FORECAST_HOURS,
) -> list[dict[str, Any]]:
    """NCEP HRRR simulated reflectivity from now through the next two hours."""
    init_stamp = _hrrr_init_stamp(str(meta.get("model_init_utc") or ""))
    if not init_stamp:
        return []
    init = pd.to_datetime(meta.get("model_init_utc"), utc=True, errors="coerce")
    if pd.isna(init):
        return []
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    horizon = clock + timedelta(hours=horizon_hours, minutes=HRRR_STEP_MINUTES)
    start = clock - timedelta(minutes=10)
    frames = []
    for minute in range(0, HRRR_MAX_MINUTE + 1, HRRR_STEP_MINUTES):
        valid = init.to_pydatetime() + timedelta(minutes=minute)
        if valid.tzinfo is None:
            valid = valid.replace(tzinfo=timezone.utc)
        if valid < start or valid > horizon:
            continue
        unix = int(valid.timestamp())
        frames.append(
            {
                "url": f"{HRRR_TILE_HOST}/hrrr::REFD-F{minute:04d}-{init_stamp}/{{z}}/{{x}}/{{y}}.png",
                "time_et": _radar_time_et(unix),
                "kind": "forecast",
                "unix": unix,
            }
        )
    return frames


def merge_radar_frames(observed: list[dict[str, Any]], forecast: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Observed RainViewer loop, then HRRR frames that start after the last observation."""
    merged = list(observed or [])
    last_obs = None
    for frame in reversed(merged):
        if frame.get("unix") is not None:
            last_obs = int(frame["unix"])
            break
    for frame in forecast or []:
        unix = frame.get("unix")
        if last_obs is not None and unix is not None and int(unix) <= last_obs:
            continue
        merged.append(frame)
    return merged


def parse_rainviewer_tile_url(payload: dict[str, Any]) -> str | None:
    """Latest observed radar tiles, transparent where there is no rain."""
    frames = parse_rainviewer_frames(payload, max_frames=1)
    return frames[-1]["url"] if frames else None


def fetch_hrrr_forecast_frames(client: httpx.Client | None = None) -> list[dict[str, Any]]:
    http = client or httpx.Client(timeout=15.0)
    owns = client is None
    try:
        response = http.get(HRRR_META_URL)
        response.raise_for_status()
        return parse_hrrr_forecast_frames(response.json())
    except (httpx.HTTPError, ValueError, TypeError):
        return []
    finally:
        if owns:
            http.close()


def fetch_radar_frames(client: httpx.Client | None = None) -> list[dict[str, Any]]:
    http = client or httpx.Client(timeout=15.0)
    owns = client is None
    try:
        observed: list[dict[str, Any]] = []
        try:
            response = http.get(RAINVIEWER_MAPS_URL)
            response.raise_for_status()
            observed = parse_rainviewer_frames(response.json())
        except (httpx.HTTPError, ValueError, TypeError):
            observed = []
        forecast = fetch_hrrr_forecast_frames(http)
        return merge_radar_frames(observed, forecast)
    finally:
        if owns:
            http.close()


def fetch_radar_tile_url(client: httpx.Client | None = None) -> str | None:
    frames = fetch_radar_frames(client)
    return frames[-1]["url"] if frames else None


def attach_hold_brief(forecast: dict[str, Any]) -> dict[str, Any]:
    """Add hold_status and hold_label so the app does not re-import classifiers."""
    alerts = forecast.get("alerts") or []
    for alert in alerts:
        alert["kind"] = nws_event_kind(str(alert.get("event") or ""))
    nws = nws_hold_status(alerts)
    implication = str(forecast.get("implication") or "")
    if forecast.get("thunderstorm") or nws == "alert" or implication.startswith("Storm"):
        status = "alert"
    elif nws == "watch" or implication.startswith("Rain") or implication.startswith("Gusty"):
        status = "watch"
    else:
        status = "clear"
    ranked = sorted(
        alerts,
        key=lambda row: {"alert": 0, "watch": 1, "clear": 2}.get(str(row.get("kind") or "clear"), 2),
    )
    label = "None"
    if status == "alert":
        label = "Storm risk"
    elif status == "watch":
        label = "Watch"
    if ranked and str(ranked[0].get("kind") or "clear") != "clear":
        label = str(ranked[0].get("event") or label)
    forecast["hold_status"] = status
    forecast["hold_label"] = label
    return forecast


def fetch_wdw_weather() -> dict[str, Any]:
    forecast = fetch_open_meteo()
    forecast["alerts"] = fetch_nws_alerts()
    forecast["implication"] = ops_implication(forecast["current"], forecast["hourly"], forecast["alerts"])
    forecast["radar_frames"] = fetch_radar_frames()
    forecast["radar_tiles"] = forecast["radar_frames"][-1]["url"] if forecast["radar_frames"] else None
    return attach_hold_brief(forecast)
