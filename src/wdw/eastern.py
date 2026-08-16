"""Format clock times in Eastern Time (America/New_York — EST/EDT)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from wdw.config import TIMEZONE

EASTERN = ZoneInfo(TIMEZONE)
TZ_LABEL = "ET"


def now_eastern() -> datetime:
    return datetime.now(EASTERN)


def to_eastern(value) -> pd.Timestamp | None:
    """Parse an ISO/timestamp and convert to America/New_York.

    Naive values are treated as already Eastern (TouringPlans park-local times).
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize(EASTERN)
    return ts.tz_convert(EASTERN)


def format_clock(value, with_tz: bool = True) -> str:
    """e.g. '8:00 AM ET'."""
    ts = to_eastern(value)
    if ts is None:
        return ""
    hour = ts.strftime("%I").lstrip("0") or "12"
    stamp = f"{hour}:{ts.strftime('%M %p')}"
    return f"{stamp} {TZ_LABEL}" if with_tz else stamp


def hour_label(hour: int) -> str:
    """Integer hour 0–23 → '8 AM'."""
    wrapped = int(hour) % 24
    dummy = datetime(2000, 1, 1, wrapped, tzinfo=EASTERN)
    hour_txt = dummy.strftime("%I").lstrip("0") or "12"
    return f"{hour_txt} {dummy.strftime('%p')}"


# WDW operating days run past midnight. Plot 6 AM → 2 AM, not 12 AM → 11 PM.
PARK_DAY_HOURS = list(range(6, 24)) + [0, 1, 2]


def park_day_labels() -> list[str]:
    return [hour_label(hour) for hour in PARK_DAY_HOURS]


def hour_et_category(hours: pd.Series) -> pd.Series:
    labels = hours.map(lambda h: hour_label(int(h)) if pd.notna(h) else pd.NA)
    return pd.Categorical(labels, categories=park_day_labels(), ordered=True)


def format_series(series: pd.Series) -> pd.Series:
    return series.map(format_clock)
