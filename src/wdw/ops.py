"""Operations attention rules for a park-shift console.

These are third-party heuristics for a portfolio dashboard, not Disney SOP.
"""

from __future__ import annotations

import pandas as pd

HOT_MINUTES = 15
VERY_HOT_MINUTES = 25
LONG_STANDBY = 60
SEVERE_STANDBY = 90

SEVERITY_ORDER = {"critical": 0, "high": 1, "watch": 2}


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
