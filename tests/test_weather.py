"""Open-Meteo / NWS weather parsing for the WDW resort area."""

from __future__ import annotations

from wdw.weather import (
    is_thunderstorm,
    nws_event_kind,
    nws_hold_status,
    ops_implication,
    parse_nws_alerts,
    parse_open_meteo,
    parse_rainviewer_frames,
    parse_rainviewer_tile_url,
    weather_label,
)


def test_weather_label_thunderstorm() -> None:
    assert weather_label(95) == "Thunderstorm"
    assert is_thunderstorm(96) is True
    assert is_thunderstorm(0) is False


def test_parse_open_meteo_current_and_hourly() -> None:
    payload = {
        "current": {
            "time": "2026-08-16T11:00",
            "temperature_2m": 88.0,
            "apparent_temperature": 95.0,
            "relative_humidity_2m": 72,
            "precipitation": 0.0,
            "weather_code": 2,
            "wind_speed_10m": 8.0,
            "wind_gusts_10m": 14.0,
            "cloud_cover": 40,
        },
        "hourly": {
            "time": ["2026-08-16T11:00", "2026-08-16T12:00", "2026-08-16T13:00"],
            "temperature_2m": [88, 90, 91],
            "precipitation_probability": [20, 45, 70],
            "precipitation": [0, 0, 0.1],
            "weather_code": [2, 80, 95],
            "wind_speed_10m": [8, 10, 12],
        },
        "daily": {
            "temperature_2m_max": [93],
            "temperature_2m_min": [76],
            "precipitation_probability_max": [70],
        },
    }
    parsed = parse_open_meteo(payload)
    assert parsed["current"]["temp_f"] == 88
    assert parsed["current"]["condition"] == "Partly cloudy"
    assert len(parsed["hourly"]) == 3
    assert parsed["today_high_f"] == 93
    assert parsed["thunderstorm"] is False


def test_ops_implication_flags_storms() -> None:
    import pandas as pd

    hourly = pd.DataFrame({"precip_chance": [20, 80, 40]})
    text = ops_implication({"weather_code": 95, "precipitation": 0, "wind_gusts": 10}, hourly)
    assert "Storm risk" in text


def test_ops_implication_uses_nws_statement_not_all_clear() -> None:
    import pandas as pd

    hourly = pd.DataFrame({"precip_chance": [10, 10, 10]})
    alerts = [{"event": "Special Weather Statement", "headline": "Storms near Orange County"}]
    text = ops_implication({"weather_code": 1, "precipitation": 0, "wind_gusts": 8}, hourly, alerts)
    assert "No weather hold" not in text
    assert "Special Weather Statement" in text
    assert nws_hold_status(alerts) == "watch"
    assert nws_event_kind("Special Weather Statement") == "watch"
    assert nws_event_kind("Severe Thunderstorm Warning") == "alert"


def test_ops_implication_thunderstorm_warning_is_alert() -> None:
    import pandas as pd

    hourly = pd.DataFrame({"precip_chance": [10]})
    alerts = [{"event": "Severe Thunderstorm Warning"}]
    text = ops_implication({"weather_code": 2, "precipitation": 0, "wind_gusts": 8}, hourly, alerts)
    assert "lightning hold" in text
    assert nws_hold_status(alerts) == "alert"


def test_parse_rainviewer_tile_url() -> None:
    url = parse_rainviewer_tile_url(
        {
            "host": "https://tilecache.rainviewer.com",
            "radar": {"past": [{"path": "/v2/radar/1710000000", "time": 1710000000}]},
        }
    )
    assert url is not None
    assert "{z}" in url and "{x}" in url and "{y}" in url
    assert url.startswith("https://tilecache.rainviewer.com/v2/radar/1710000000/")
    frames = parse_rainviewer_frames(
        {
            "host": "https://tilecache.rainviewer.com",
            "radar": {
                "past": [
                    {"path": "/v2/radar/1710000000", "time": 1710000000},
                    {"path": "/v2/radar/1710000300", "time": 1710000300},
                    {"path": "/v2/radar/1710000600", "time": 1710000600},
                ]
            },
        }
    )
    assert len(frames) == 3
    assert frames[-1]["url"].endswith("/2/1_1.png")
    assert "{z}" in frames[0]["url"]
    assert frames[0]["time_et"].endswith("ET")
    assert frames[-1]["time_et"] != frames[0]["time_et"]


def test_parse_nws_alerts() -> None:
    payload = {
        "features": [
            {
                "properties": {
                    "event": "Severe Thunderstorm Warning",
                    "severity": "Severe",
                    "headline": "Severe Thunderstorm Warning issued by NWS Melbourne FL",
                    "areaDesc": "Orange; Osceola",
                    "instruction": "Move indoors.",
                }
            },
            {
                "properties": {
                    "event": "Rip Current Statement",
                    "headline": "Rip Current Statement by NWS Melbourne FL",
                    "areaDesc": "Brevard",
                }
            },
        ]
    }
    alerts = parse_nws_alerts(payload)
    assert len(alerts) == 1
    assert alerts[0]["event"] == "Severe Thunderstorm Warning"
    assert "Melbourne" not in alerts[0]["headline"]
    assert "Lake Buena Vista" in alerts[0]["headline"]
    assert alerts[0]["kind"] == "alert"
