"""Warehouse loaders for TouringPlans-style CSVs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from wdw.config import CLOSED_POSTED_WAIT
from wdw.warehouse import build_hourly, load_attraction_csv, load_metadata


def test_load_attraction_csv_treats_minus_999_as_closed(tmp_path: Path) -> None:
    csv = tmp_path / "pirates_of_caribbean.csv"
    csv.write_text(
        "date,datetime,SACTMIN,SPOSTMIN\n"
        "01/01/2018,2018-01-01 10:00:00,12,25\n"
        "01/01/2018,2018-01-01 10:15:00,,-999\n",
        encoding="utf-8",
    )
    spec = {
        "key": "pirates_of_caribbean",
        "file": "pirates_of_caribbean.csv",
        "name": "Pirates of the Caribbean",
        "park": "magic_kingdom",
        "live_entity_id": "x",
        "live_name": "Pirates of the Caribbean",
    }
    frame = load_attraction_csv(spec, path=csv)
    assert len(frame) == 2
    assert frame.loc[0, "posted_wait"] == 25
    assert pd.isna(frame.loc[1, "posted_wait"])
    assert CLOSED_POSTED_WAIT == -999


def test_load_metadata_holiday_and_emh(tmp_path: Path) -> None:
    csv = tmp_path / "touringplans_metadata.csv"
    csv.write_text(
        "DATE,SEASON,HOLIDAY,HOLIDAYN,WDWTICKETSEASON,WDWMEANTEMP,WEATHER_WDWPRECIP,"
        "MKEMHMORN,EPEMHMORN,HSEMHMORN,AKEMHMORN,MKEMHEVE,EPEMHEVE,HSEMHEVE,AKEMHEVE,"
        "MKHOURS,EPHOURS,HSHOURS,AKHOURS\n"
        "01/01/2018,CHRISTMAS,1,nyd,peak,70.0,0.1,1,0,0,0,0,0,0,0,16,12,14,11\n",
        encoding="utf-8",
    )
    meta = load_metadata(csv)
    assert len(meta) == 1
    assert int(meta.loc[0, "holiday"]) == 1
    assert int(meta.loc[0, "mk_emh_morn"]) == 1
    assert float(meta.loc[0, "mk_hours"]) == 16


def test_build_hourly_joins_early_entry(tmp_path: Path) -> None:
    waits = pd.DataFrame(
        {
            "attraction_key": ["pirates_of_caribbean"],
            "attraction_name": ["Pirates of the Caribbean"],
            "park_key": ["magic_kingdom"],
            "park_name": ["Magic Kingdom Park"],
            "live_entity_id": ["x"],
            "live_name": ["Pirates of the Caribbean"],
            "park_date": [pd.Timestamp("2018-01-01")],
            "observed_at": [pd.Timestamp("2018-01-01 10:00:00")],
            "posted_wait": [25],
            "actual_wait": [12],
        }
    )
    meta = pd.DataFrame(
        {
            "park_date": [pd.Timestamp("2018-01-01")],
            "season": ["CHRISTMAS"],
            "holiday": [1],
            "holiday_name": ["nyd"],
            "ticket_season": ["peak"],
            "mk_emh_morn": [1],
            "ep_emh_morn": [0],
            "hs_emh_morn": [0],
            "ak_emh_morn": [0],
        }
    )
    hourly = build_hourly(waits, meta)
    assert int(hourly.loc[0, "early_entry"]) == 1
    assert int(hourly.loc[0, "is_holiday"]) == 1
    assert hourly.loc[0, "hour"] == 10
