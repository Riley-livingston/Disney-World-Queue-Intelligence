"""Operations attention rules for a park-shift console.

These are third-party heuristics for a portfolio dashboard, not Disney SOP.
"""

from __future__ import annotations

import pandas as pd

from wdw.eastern import now_eastern, to_eastern

HOT_MINUTES = 15
VERY_HOT_MINUTES = 25
LONG_STANDBY = 60
SEVERE_STANDBY = 90

SEVERITY_ORDER = {"critical": 0, "high": 1, "watch": 2}

# Unique attractions in the same park whose return windows land in one hour.
STACK_THRESHOLD = 3
INVENTORY_BY_STATE = {
    "AVAILABLE": "available",
    "FINISHED": "exhausted",
    "TEMP_FULL": "paused",
    "NOT_AVAILABLE_YET": "upcoming",
}
INVENTORY_RANK = {"exhausted": 0, "paused": 1, "available": 2, "upcoming": 3}
RETURN_PRODUCTS = (
    ("Lightning Lane", "return_time_state", "return_start", "return_end"),
    ("Individual Lightning Lane", "paid_return_state", "paid_return_start", "paid_return_end"),
)


def _num(value) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    return float(number)


def classify_attraction(row: dict) -> dict | None:
    """Return an attention item, or None if the ride does not need a shift flag."""
    name = row.get("entity_name") or row.get("attraction_name")
    park = row.get("park_name")
    status = str(row.get("status") or "").upper()
    wait = _num(row.get("standby_wait"))
    delta = _num(row.get("delta_vs_expected"))
    park_has_open = bool(row.get("park_has_open"))

    if status == "DOWN":
        return {
            "severity": "critical",
            "priority": 100,
            "park_name": park,
            "attraction": name,
            "status": status,
            "standby_min": wait,
            "vs_expected_min": delta,
            "signal": "Down",
        }

    if status != "OPERATING":
        return None

    if delta is not None and delta >= VERY_HOT_MINUTES:
        return {
            "severity": "high",
            "priority": 80 + min(delta, 40),
            "park_name": park,
            "attraction": name,
            "status": status,
            "standby_min": wait,
            "vs_expected_min": delta,
            "signal": f"{int(round(delta))} min above expected",
        }

    if wait is not None and wait >= SEVERE_STANDBY:
        return {
            "severity": "high",
            "priority": 70 + min(wait / 10, 20),
            "park_name": park,
            "attraction": name,
            "status": status,
            "standby_min": wait,
            "vs_expected_min": delta,
            "signal": f"{int(wait)} min standby",
        }

    if delta is not None and delta >= HOT_MINUTES:
        return {
            "severity": "watch",
            "priority": 45 + delta,
            "park_name": park,
            "attraction": name,
            "status": status,
            "standby_min": wait,
            "vs_expected_min": delta,
            "signal": f"{int(round(delta))} min above expected",
        }

    if wait is not None and wait >= LONG_STANDBY:
        return {
            "severity": "watch",
            "priority": 40 + wait / 10,
            "park_name": park,
            "attraction": name,
            "status": status,
            "standby_min": wait,
            "vs_expected_min": delta,
            "signal": f"{int(wait)} min standby",
        }

    return None


def park_open_flags(live: pd.DataFrame) -> dict[str, bool]:
    if live is None or live.empty or "status" not in live.columns:
        return {}
    work = live
    if "entity_type" in work.columns:
        work = work.loc[work["entity_type"] == "ATTRACTION"]
    flags: dict[str, bool] = {}
    for park, group in work.groupby("park_name", dropna=True):
        flags[str(park)] = bool((group["status"] == "OPERATING").any())
    return flags


def attach_expected(live: pd.DataFrame, scored: pd.DataFrame) -> pd.DataFrame:
    work = live.copy()
    if scored is None or scored.empty:
        work["expected_wait"] = pd.NA
        work["delta_vs_expected"] = pd.NA
        return work
    cols = [col for col in ("entity_id", "expected_wait", "delta_vs_expected") if col in scored.columns]
    extra = scored[cols].drop_duplicates("entity_id")
    work = work.merge(extra, on="entity_id", how="left")
    return work


def attention_queue(live: pd.DataFrame, scored: pd.DataFrame | None = None) -> pd.DataFrame:
    """Ranked list of attractions a shift lead would want on a radio call."""
    if live is None or live.empty:
        return pd.DataFrame()
    work = live.copy()
    if "entity_type" in work.columns:
        work = work.loc[work["entity_type"] == "ATTRACTION"]
    work = attach_expected(work, scored if scored is not None else pd.DataFrame())
    open_flags = park_open_flags(work)
    work["park_has_open"] = work["park_name"].map(open_flags).fillna(False)
    items = []
    for rec in work.to_dict(orient="records"):
        item = classify_attraction(rec)
        if item:
            items.append(item)
    if not items:
        return pd.DataFrame()
    out = pd.DataFrame(items)
    out["severity_rank"] = out["severity"].map(SEVERITY_ORDER)
    return out.sort_values(["severity_rank", "priority"], ascending=[True, False]).drop(
        columns=["severity_rank", "priority"]
    ).reset_index(drop=True)


def current_vs_typical(curve: pd.DataFrame, live_wait, hour: int) -> dict:
    """Compare this hour's typical posted wait to the live standby."""
    empty = {"typical": None, "live": _num(live_wait), "delta": None, "hour": hour}
    if curve is None or curve.empty or "hour" not in curve.columns:
        return empty
    slice_ = curve.loc[pd.to_numeric(curve["hour"], errors="coerce") == hour]
    if slice_.empty:
        return empty
    if "n" in slice_.columns and float(pd.to_numeric(slice_["n"].iloc[0], errors="coerce") or 0) <= 0:
        return empty
    typical = _num(slice_["posted_median"].iloc[0])
    live = _num(live_wait)
    delta = None if typical is None or live is None else live - typical
    return {"typical": typical, "live": live, "delta": delta, "hour": hour}


def _state_token(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text.upper()


def _as_eastern_now(now) -> pd.Timestamp:
    stamp = to_eastern(now) if now is not None else to_eastern(now_eastern())
    if stamp is None:
        stamp = to_eastern(now_eastern())
    return stamp


def format_lead_minutes(minutes) -> str:
    """Human lead time, e.g. '2h 15m', '45 min', or 'Now' if the window has started."""
    number = _num(minutes)
    if number is None:
        return "n/a"
    rounded = int(round(number))
    if rounded <= 0:
        return "Now"
    hours, mins = divmod(rounded, 60)
    if hours <= 0:
        return f"{mins} min"
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"


def return_time_pressure(live: pd.DataFrame, now=None) -> pd.DataFrame:
    """Lightning Lane tightness from ThemeParks.wiki queue fields.

    One row per attraction and product (Lightning Lane vs Individual Lightning Lane).
    Lead minutes are how far out the next posted window starts. Overlapping hours are when
    three or more attractions in the same park send Lightning Lane guests into the same clock hour.
    """
    if live is None or live.empty:
        return pd.DataFrame()

    work = live.copy()
    if "entity_type" in work.columns:
        work = work.loc[work["entity_type"] == "ATTRACTION"]
    if work.empty:
        return pd.DataFrame()

    now_ts = _as_eastern_now(now)
    rows: list[dict] = []
    for rec in work.to_dict(orient="records"):
        standby = _num(rec.get("standby_wait"))
        for product, state_col, start_col, end_col in RETURN_PRODUCTS:
            state = _state_token(rec.get(state_col))
            start = to_eastern(rec.get(start_col))
            end = to_eastern(rec.get(end_col))
            if not state and start is None:
                continue
            if state in {"", "NONE", "CLOSED"} and start is None:
                continue
            if state == "NOT_AVAILABLE_YET" and start is None:
                continue
            inventory = INVENTORY_BY_STATE.get(state)
            if inventory is None:
                if start is None:
                    continue
                inventory = "available"
            lead = None
            hour = pd.NA
            if start is not None:
                lead = (start - now_ts).total_seconds() / 60.0
                hour = int(start.hour)
            rows.append(
                {
                    "park_name": rec.get("park_name"),
                    "attraction": rec.get("entity_name") or rec.get("attraction_name"),
                    "product": product,
                    "state": state or "AVAILABLE",
                    "inventory": inventory,
                    "return_start": start,
                    "return_end": end,
                    "lead_minutes": lead,
                    "hour": hour,
                    "standby_min": standby,
                }
            )

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    out["hour"] = pd.to_numeric(out["hour"], errors="coerce").astype("Int64")
    windowed = out.dropna(subset=["hour"]).drop_duplicates(["park_name", "attraction", "hour"])
    if windowed.empty:
        out["windows_in_hour"] = 0
        out["stacked"] = False
    else:
        counts = windowed.groupby(["park_name", "hour"], dropna=True).size().rename("windows_in_hour")
        out = out.merge(counts, on=["park_name", "hour"], how="left")
        out["windows_in_hour"] = pd.to_numeric(out["windows_in_hour"], errors="coerce").fillna(0).astype(int)
        out["stacked"] = out["windows_in_hour"] >= STACK_THRESHOLD
    out["inventory_rank"] = out["inventory"].map(INVENTORY_RANK).fillna(9)
    out["_lead_sort"] = pd.to_numeric(out["lead_minutes"], errors="coerce").fillna(-10_000)
    return (
        out.sort_values(["inventory_rank", "_lead_sort"], ascending=[True, False])
        .drop(columns=["inventory_rank", "_lead_sort"])
        .reset_index(drop=True)
    )


def return_pressure_kpis(pressure: pd.DataFrame) -> dict:
    empty = {
        "available": 0,
        "exhausted": 0,
        "paused": 0,
        "farthest_minutes": None,
        "farthest_attraction": None,
        "stacked_hours": 0,
        "busiest_count": None,
        "busiest_park": None,
        "busiest_hour": None,
    }
    if pressure is None or pressure.empty:
        return empty

    def _unique(inventory: str) -> int:
        slice_ = pressure.loc[pressure["inventory"] == inventory]
        if slice_.empty:
            return 0
        return int(slice_["attraction"].nunique())

    kpis = {
        **empty,
        "available": _unique("available"),
        "exhausted": _unique("exhausted"),
        "paused": _unique("paused"),
    }
    available = pressure.loc[pressure["inventory"] == "available"].copy()
    leads = pd.to_numeric(available.get("lead_minutes"), errors="coerce")
    future = available.loc[leads > 0]
    if not future.empty:
        far_idx = pd.to_numeric(future["lead_minutes"], errors="coerce").idxmax()
        far = future.loc[far_idx]
        kpis["farthest_minutes"] = float(far["lead_minutes"])
        kpis["farthest_attraction"] = far.get("attraction")
    overlap = overlapping_hours(pressure)
    kpis["stacked_hours"] = int(len(overlap))
    if not overlap.empty:
        top = overlap.iloc[0]
        kpis["busiest_count"] = int(top["attractions"])
        kpis["busiest_park"] = top.get("park_name")
        kpis["busiest_hour"] = int(top["hour"])
    return kpis


def return_windows_by_hour(pressure: pd.DataFrame) -> pd.DataFrame:
    """Unique attractions with a posted return window, by park and hour."""
    if pressure is None or pressure.empty or "hour" not in pressure.columns:
        return pd.DataFrame(columns=["park_name", "hour", "attractions"])
    windowed = pressure.dropna(subset=["hour"]).drop_duplicates(["park_name", "attraction", "hour"])
    if windowed.empty:
        return pd.DataFrame(columns=["park_name", "hour", "attractions"])
    counts = (
        windowed.groupby(["park_name", "hour"], dropna=True)
        .size()
        .reset_index(name="attractions")
        .sort_values(["hour", "park_name"])
        .reset_index(drop=True)
    )
    counts["hour"] = counts["hour"].astype(int)
    return counts


def overlapping_hours(pressure: pd.DataFrame, min_attractions: int = STACK_THRESHOLD) -> pd.DataFrame:
    """Park clock hours where several attractions send Lightning Lane guests at once."""
    counts = return_windows_by_hour(pressure)
    if counts.empty:
        return counts
    return (
        counts.loc[counts["attractions"] >= min_attractions]
        .sort_values(["attractions", "hour"], ascending=[False, True])
        .reset_index(drop=True)
    )
