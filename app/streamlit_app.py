"""Walt Disney World Queue Intelligence — Streamlit guest-operations brief."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from wdw.config import METRICS_JSON, SAMPLE_HOURLY_PARQUET
from wdw.eastern import format_clock, format_series, hour_et_category, now_eastern, park_day_labels
from wdw.ingest_live import latest_live_frame
from wdw.model import expected_wait, posted_vs_actual, typical_day_curve
from wdw.themeparks import CREDIT, ThemeParksClient, ThemeParksError, flatten_live
from wdw.typical import attraction_catalog, combine_observations, empty_typical_day
from wdw.warehouse import load_hourly

NAVY = "#0A1628"
GOLD = "#C4A35A"
CREAM = "#F4EFE6"
SLATE = "#4A5568"
CHART_COLORS = ["#0A1628", "#C4A35A", "#2C5282", "#9B6B2F", "#1A365D"]

st.set_page_config(
    page_title="WDW Queue Intelligence",
    layout="wide",
)

st.markdown(
    f"""
    <style>
      .stApp {{ background: {CREAM}; color: {NAVY}; }}
      h1, h2, h3 {{ color: {NAVY} !important; font-family: Georgia, serif; }}
      [data-testid="stMetricValue"] {{ color: {NAVY}; }}
      .credit {{ color: {SLATE}; font-size: 0.85rem; }}
      .disclaimer {{ color: {SLATE}; font-size: 0.8rem; margin-top: 2rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300, show_spinner="Fetching live park data...")
def fetch_live() -> pd.DataFrame:
    client = ThemeParksClient()
    snapshots = client.wdw_live()
    rows = flatten_live(snapshots)
    frame = pd.DataFrame(rows)
    return frame


@st.cache_data(show_spinner=False)
def historical() -> pd.DataFrame:
    return load_hourly(prefer_full=True)


@st.cache_data(ttl=300, show_spinner=False)
def typical_day_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Catalog + precomputed curves. Switching rides then only filters this table."""
    hourly = historical()
    live, _source = load_live_board()
    catalog = attraction_catalog(hourly, live)
    curves = typical_day_curve(combine_observations(hourly, live))
    return catalog, curves


def load_live_board() -> tuple[pd.DataFrame, str]:
    try:
        live = fetch_live()
        return live, "live"
    except ThemeParksError:
        cached = latest_live_frame()
        if cached is not None and not cached.empty:
            return cached, "snapshot"
        return pd.DataFrame(), "unavailable"


def eastern_hour_axis(fig: go.Figure) -> go.Figure:
    labels = park_day_labels()
    fig.update_xaxes(
        categoryorder="array",
        categoryarray=labels,
        title="Hour of day (Eastern Time)",
    )
    return fig


def style_fig(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=NAVY, family="Georgia, serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=40, r=20, t=60, b=40),
    )
    fig.update_xaxes(gridcolor="#E2D6C2", zeroline=False)
    fig.update_yaxes(gridcolor="#E2D6C2", zeroline=False)
    return fig


def page_live(hourly: pd.DataFrame) -> None:
    st.subheader("Live operations board")
    st.caption("Four Orlando theme parks. Standby waits, downs, and Lightning Lane / return times when the API provides them.")
    live, source = load_live_board()
    if live.empty:
        st.warning("Live ThemeParks.wiki data is unavailable. Historical pages still work from the local warehouse.")
        return
    if source == "snapshot":
        st.info("Showing the last saved snapshot because a live fetch failed.")
    elif source == "live":
        st.caption(f"{CREDIT} · cached for 5 minutes · fetched {format_clock(now_eastern())}")

    attractions = live.loc[live["entity_type"] == "ATTRACTION"].copy()
    if "forecast" in attractions.columns:
        attractions = attractions.drop(columns=["forecast"])
    attractions["standby_wait"] = pd.to_numeric(attractions["standby_wait"], errors="coerce")
    operating = attractions.loc[attractions["status"] == "OPERATING"]
    downs = attractions.loc[attractions["status"].isin(["DOWN", "CLOSED"])]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Attractions reporting", f"{len(attractions):,}")
    col2.metric("Open with a wait", f"{operating['standby_wait'].notna().sum():,}")
    longest = operating.dropna(subset=["standby_wait"]).nlargest(1, "standby_wait")
    if not longest.empty:
        row = longest.iloc[0]
        col3.metric("Longest standby", f"{int(row['standby_wait'])} min", row["entity_name"])
    down_count = int((attractions["status"] == "DOWN").sum())
    col4.metric("Reported down", down_count)

    parks = sorted(attractions["park_name"].dropna().unique())
    selected = st.multiselect("Parks", parks, default=parks)
    view = attractions.loc[attractions["park_name"].isin(selected)].copy()
    view["standby_wait"] = pd.to_numeric(view["standby_wait"], errors="coerce")

    top = (
        view.dropna(subset=["standby_wait"])
        .sort_values("standby_wait", ascending=False)
        .head(15)
    )
    fig = px.bar(
        top.sort_values("standby_wait"),
        x="standby_wait",
        y="entity_name",
        color="park_name",
        color_discrete_sequence=CHART_COLORS,
        labels={"standby_wait": "Standby wait (minutes)", "entity_name": "Attraction", "park_name": "Park"},
        title="Longest standby waits right now",
    )
    st.plotly_chart(style_fig(fig), width="stretch")

    left, right = st.columns(2)
    with left:
        st.markdown("**Currently down or closed**")
        down_view = downs.loc[downs["park_name"].isin(selected), ["park_name", "entity_name", "status"]]
        st.dataframe(down_view.rename(columns={"park_name": "Park", "entity_name": "Attraction", "status": "Status"}), hide_index=True, width="stretch")
    with right:
        st.markdown("**Lightning Lane / return windows**")
        ll = view.loc[view["return_time_state"].notna() | view["paid_return_state"].notna()]
        if ll.empty:
            st.caption("No return-time fields in this snapshot.")
        else:
            shown = ll[
                [
                    "park_name",
                    "entity_name",
                    "return_time_state",
                    "return_start",
                    "paid_return_state",
                ]
            ].copy()
            shown["return_start"] = format_series(shown["return_start"])
            st.dataframe(
                shown.rename(
                    columns={
                        "park_name": "Park",
                        "entity_name": "Attraction",
                        "return_time_state": "Return",
                        "return_start": "Return start (ET)",
                        "paid_return_state": "Paid return",
                    }
                ),
                hide_index=True,
                width="stretch",
            )

    hours = (
        view.dropna(subset=["opens_at"])
        .drop_duplicates("park_name")[["park_name", "opens_at", "closes_at"]]
        .sort_values("park_name")
    )
    if not hours.empty:
        hours = hours.copy()
        hours["opens_at"] = format_series(hours["opens_at"])
        hours["closes_at"] = format_series(hours["closes_at"])
        st.markdown("**Today's operating hours (Eastern Time)**")
        st.dataframe(
            hours.rename(columns={"park_name": "Park", "opens_at": "Opens (ET)", "closes_at": "Closes (ET)"}),
            hide_index=True,
            width="stretch",
        )


def page_typical_day() -> None:
    st.subheader("Shape of a park day")
    st.caption(
        "Every attraction at the four Orlando theme parks. Posted wait median and "
        "25th–75th percentile by hour (Eastern Time). TouringPlans multi-year posted "
        "waits when we have them; otherwise the ThemeParks.wiki hourly posted forecast — "
        "not the live standby number. Actual wait is a TouringPlans guest report and "
        "only exists for those headliners. Closed hours are 0."
    )
    catalog, curves = typical_day_frames()
    if catalog.empty:
        st.warning("No attractions available for a typical-day curve.")
        return
    parks = sorted(catalog["park_name"].dropna().unique())
    park = st.selectbox("Park", parks)
    names = sorted(catalog.loc[catalog["park_name"] == park, "attraction_name"].unique())
    default = "Seven Dwarfs Mine Train" if "Seven Dwarfs Mine Train" in names else names[0]
    picked = st.selectbox("Attraction", names, index=names.index(default))
    row = catalog.loc[
        (catalog["park_name"] == park) & (catalog["attraction_name"] == picked)
    ].iloc[0]
    curve = curves.loc[curves["attraction_name"] == picked]
    if curve.empty:
        curve = empty_typical_day(picked, park, str(row["attraction_key"]))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=curve["hour_et"],
            y=curve["posted_p75"],
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=curve["hour_et"],
            y=curve["posted_p25"],
            fill="tonexty",
            fillcolor="rgba(196,163,90,0.25)",
            line=dict(width=0),
            name="25th–75th percentile posted wait",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=curve["hour_et"],
            y=curve["posted_median"],
            mode="lines+markers",
            line=dict(color=NAVY, width=3),
            name="Median posted wait",
        )
    )
    if curve.get("has_actual") is not None and float(curve["has_actual"].fillna(0).max()) > 0:
        fig.add_trace(
            go.Scatter(
                x=curve["hour_et"],
                y=curve["actual_median"],
                mode="lines",
                line=dict(color=GOLD, width=2, dash="dash"),
                name="Median actual wait (TouringPlans)",
            )
        )
    fig.update_layout(
        title=f"Typical day · {picked}",
        yaxis_title="Wait (minutes)",
        yaxis=dict(rangemode="tozero"),
    )
    eastern_hour_axis(fig)
    st.plotly_chart(style_fig(fig), width="stretch", key=f"typical-day-{park}-{picked}")
    if row.get("has_touringplans"):
        st.caption(
            "TouringPlans historical posted waits only — live standby is not mixed in. "
            "Closed hours are 0. Actual wait is TouringPlans guest reports."
        )
    else:
        st.caption(
            "No TouringPlans history for this attraction. Posted median / percentiles "
            "come from the ThemeParks.wiki hourly posted forecast (not live standby). "
            "The band is narrow until more forecast days accumulate. Closed hours are 0."
        )

    compare = st.checkbox("Compare TouringPlans headliners")
    if compare:
        headliners = set(catalog.loc[catalog["has_touringplans"], "attraction_name"])
        all_curves = curves.loc[curves["attraction_name"].isin(headliners)]
        fig2 = px.line(
            all_curves,
            x="hour_et",
            y="posted_median",
            color="attraction_name",
            labels={"hour_et": "Hour of day (Eastern Time)", "posted_median": "Median posted wait (minutes)", "attraction_name": "Attraction"},
            title="Typical-day posted waits, TouringPlans headliners",
        )
        fig2.update_yaxes(rangemode="tozero")
        eastern_hour_axis(fig2)
        st.plotly_chart(style_fig(fig2), width="stretch", key="typical-day-compare")


def page_posted_vs_actual(hourly: pd.DataFrame) -> None:
    st.subheader("Posted vs actual wait")
    st.caption(
        "Posted standby is a guest-facing estimate. Actual wait is what a guest reported standing in line. "
        "The gap is a communication buffer, not just a queueing error."
    )
    summary = posted_vs_actual(hourly)
    overall_bias = float(hourly["posted_minus_actual"].median()) if "posted_minus_actual" in hourly else float("nan")
    c1, c2, c3 = st.columns(3)
    c1.metric("Attractions", f"{len(summary):,}")
    c2.metric("Median posted − actual", f"{overall_bias:.1f} min")
    c3.metric("Hours with both measures", f"{int(summary['n'].sum()):,}")

    fig = px.bar(
        summary.sort_values("bias_mean"),
        x="bias_mean",
        y="attraction_name",
        color="park_name",
        color_discrete_sequence=CHART_COLORS,
        labels={"bias_mean": "Mean posted minus actual (minutes)", "attraction_name": "Attraction", "park_name": "Park"},
        title="How much posted waits overshoot actual waits",
    )
    st.plotly_chart(style_fig(fig), width="stretch")

    by_hour = (
        hourly.dropna(subset=["posted_minus_actual"])
        .groupby("hour", observed=True)["posted_minus_actual"]
        .median()
        .reset_index()
    )
    by_hour["hour_et"] = hour_et_category(by_hour["hour"])
    fig_h = px.line(
        by_hour.sort_values("hour_et"),
        x="hour_et",
        y="posted_minus_actual",
        markers=True,
        labels={"hour_et": "Hour of day (Eastern Time)", "posted_minus_actual": "Median posted − actual (minutes)"},
        title="Posted-wait buffer by hour of day (Eastern Time)",
    )
    fig_h.update_traces(line_color=NAVY)
    eastern_hour_axis(fig_h)
    st.plotly_chart(style_fig(fig_h), width="stretch")
    st.dataframe(
        summary.rename(
            columns={
                "attraction_name": "Attraction",
                "park_name": "Park",
                "posted_median": "Posted median",
                "actual_median": "Actual median",
                "bias_mean": "Mean buffer",
                "bias_median": "Median buffer",
                "n": "Hours",
            }
        ).drop(columns=["attraction_key"]),
        hide_index=True,
        width="stretch",
    )


def page_now_vs_expected(hourly: pd.DataFrame) -> None:
    st.subheader("Now vs expected")
    st.caption(
        "An explainable baseline (hour, weekday, month, holiday, early entry, attraction) scored against live standby. "
        "This is not a claim to beat Disney's own wait system."
    )
    live, source = load_live_board()
    if live.empty:
        st.warning("Need live or snapshot data to compare against the baseline.")
        return
    scored = expected_wait(live, hourly)
    if scored.empty:
        st.warning("None of the live attractions matched the historical headliner map.")
        return
    scored = scored.copy()
    scored["expected_wait"] = scored["expected_wait"].round(1)
    scored["delta_vs_expected"] = scored["delta_vs_expected"].round(1)

    hotter = scored.loc[scored["delta_vs_expected"] > 5]
    cooler = scored.loc[scored["delta_vs_expected"] < -5]
    c1, c2, c3 = st.columns(3)
    c1.metric("Mapped headliners live", f"{len(scored)}")
    c2.metric("Running hotter than expected", f"{len(hotter)}")
    c3.metric("Running cooler than expected", f"{len(cooler)}")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=scored["entity_name"],
            x=scored["expected_wait"],
            name="Expected (baseline)",
            orientation="h",
            marker_color=GOLD,
        )
    )
    fig.add_trace(
        go.Bar(
            y=scored["entity_name"],
            x=scored["standby_wait"],
            name="Live standby",
            orientation="h",
            marker_color=NAVY,
        )
    )
    fig.update_layout(
        barmode="group",
        title="Live standby vs historical baseline",
        xaxis_title="Wait (minutes)",
        yaxis_title="Attraction",
    )
    st.plotly_chart(style_fig(fig), width="stretch")

    if METRICS_JSON.exists():
        import json

        metrics = json.loads(METRICS_JSON.read_text(encoding="utf-8"))
        st.markdown(
            f"**Holdout MAE:** {metrics['mae_minutes']} min vs naive same-hour/weekday median "
            f"**{metrics['naive_mae_minutes']} min** "
            f"(lift {metrics['mae_lift_vs_naive']} min). "
            f"Train {metrics['n_train']:,} hours, test {metrics['n_test']:,} hours."
        )
    st.caption(f"Comparison source: {source}. {CREDIT}")


def main() -> None:
    st.title("WDW Queue Intelligence")
    st.markdown(
        "A guest-operations brief for Walt Disney World in Orlando: how waits behave, "
        "where posted times diverge from reality, and what we should expect right now."
    )
    try:
        hourly = historical()
        using_sample = not (hourly is not None and len(hourly) > 20000) and SAMPLE_HOURLY_PARQUET.exists()
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    page = st.sidebar.radio(
        "Briefing",
        ["Live board", "Typical day", "Posted vs actual", "Now vs expected"],
    )
    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Not affiliated with The Walt Disney Company. Historical waits: TouringPlans.com. "
        f"Live waits: {CREDIT}."
    )
    if using_sample and not hourly.empty:
        st.sidebar.info("Using the compact sample warehouse. Run `wdw-ingest-history` and `wdw-build` for the full series.")

    if page == "Live board":
        page_live(hourly)
    elif page == "Typical day":
        page_typical_day()
    elif page == "Posted vs actual":
        page_posted_vs_actual(hourly)
    else:
        page_now_vs_expected(hourly)

    st.markdown(
        f"<p class='disclaimer'>Independent portfolio project. Wait times are third-party observations, not official Disney data. {CREDIT}</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
