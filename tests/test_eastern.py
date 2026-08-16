"""Eastern Time formatting helpers."""

from __future__ import annotations

from wdw.eastern import format_clock, hour_label, now_eastern, park_day_labels, to_eastern


def test_iso_offset_converts_to_eastern_clock() -> None:
    # 12:00 UTC in August is 8:00 AM EDT.
    assert format_clock("2026-08-15T12:00:00Z") == "8:00 AM ET"
    assert format_clock("2026-08-15T08:00:00-04:00") == "8:00 AM ET"


def test_naive_timestamp_stays_eastern() -> None:
    assert format_clock("2026-01-15 08:00:00") == "8:00 AM ET"


def test_hour_label() -> None:
    assert hour_label(8) == "8 AM"
    assert hour_label(0) == "12 AM"
    assert hour_label(13) == "1 PM"


def test_park_day_puts_midnight_at_end() -> None:
    labels = park_day_labels()
    assert labels[0] == "6 AM"
    assert labels[-1] == "2 AM"
    assert "12 AM" not in labels[:4]


def test_now_eastern_has_zone() -> None:
    now = now_eastern()
    assert str(now.tzinfo) in {"America/New_York", "EST", "EDT"} or now.tzinfo is not None
    assert to_eastern("2026-08-15T12:00:00+00:00").hour == 8
