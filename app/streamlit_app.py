"""Disney World Queue Intelligence — Streamlit guest-operations brief."""

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
import pydeck as pdk
import streamlit as st

from wdw.config import SAMPLE_HOURLY_PARQUET
from wdw.eastern import format_clock, format_series, hour_et_category, hour_label, now_eastern, park_day_labels
from wdw.ingest_live import latest_live_frame
from wdw.model import expected_wait, posted_vs_actual
from wdw.ops import attention_queue, current_vs_typical
from wdw.themeparks import CREDIT, ThemeParksClient, ThemeParksError, flatten_live
from wdw.typical import (
    attraction_catalog,
    empty_typical_day,
    explode_forecasts,
    has_forecast_series,
    has_typical_series,
    observations_from_hourly,
    typical_day_curve,
)
from wdw.warehouse import load_hourly
from wdw.weather import (
    PARK_POINTS,
    WDW_LATITUDE,
    WDW_LONGITUDE,
    WEATHER_CREDIT,
    WeatherError,
    fetch_wdw_weather,
)

NAVY = "#12264A"
ROYAL = "#1B4F9C"
GOLD = "#F0C14A"
CREAM = "#F7F1E6"
PARCHMENT = "#EDE4D4"
SLATE = "#4A5568"
LAGOON = "#0077B6"
STUDIO_RED = "#C8102E"
CANOPY = "#1F7A4D"
# Walt Disney World–inspired (not official Disney brand tokens).
CHART_COLORS = [ROYAL, GOLD, STUDIO_RED, CANOPY, LAGOON]
PARK_COLORS = {
    "Magic Kingdom Park": ROYAL,
    "EPCOT": LAGOON,
    "Disney's Hollywood Studios": STUDIO_RED,
    "Disney's Animal Kingdom Theme Park": CANOPY,
}
PARK_RIDE_COLORS = {
    "Magic Kingdom Park": [ROYAL, GOLD, "#C41E3A", "#5B8DEF", "#7B5EA7"],
    "EPCOT": [LAGOON, "#00A3A1", "#6B3FA0", "#E87722", "#89CFF0"],
    "Disney's Hollywood Studios": [STUDIO_RED, GOLD, "#1A1A1A", "#E87722", "#4A90A4"],
    "Disney's Animal Kingdom Theme Park": [CANOPY, "#C45C26", "#8B5A2B", GOLD, "#2E86AB"],
}

st.set_page_config(
    page_title="Disney World Queue Intelligence",
    page_icon="✨",
    layout="wide",
)

st.markdown(
    f"""
    <style>
      .stApp {{
        background:
          radial-gradient(ellipse at 12% -10%, rgba(240,193,74,0.22), transparent 42%),
          radial-gradient(ellipse at 88% -8%, rgba(27,79,156,0.14), transparent 40%),
          radial-gradient(ellipse at 80% 110%, rgba(31,122,77,0.08), transparent 36%),
          {CREAM};
        color: {NAVY};
      }}
      h1, h2, h3 {{
        color: {NAVY} !important;
        font-family: Georgia, "Palatino Linotype", Palatino, serif;
        letter-spacing: 0.01em;
      }}
      [data-testid="stMetric"] {{
        background: rgba(255,253,248,0.9);
        border-left: 4px solid {GOLD};
        padding: 0.65rem 0.9rem 0.75rem;
        border-radius: 0 10px 10px 0;
        box-shadow: 0 1px 0 {PARCHMENT};
      }}
      [data-testid="stMetricValue"] {{ color: {NAVY}; font-family: Georgia, serif; }}
      [data-testid="stMetricLabel"] {{ color: {SLATE}; }}
      section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {NAVY} 0%, #0A1628 100%);
        border-right: 3px solid {GOLD};
      }}
      section[data-testid="stSidebar"] h1,
      section[data-testid="stSidebar"] h2,
      section[data-testid="stSidebar"] h3,
      section[data-testid="stSidebar"] p,
      section[data-testid="stSidebar"] span,
      section[data-testid="stSidebar"] label,
      section[data-testid="stSidebar"] li,
      section[data-testid="stSidebar"] .stMarkdown {{
        color: {CREAM} !important;
      }}
      section[data-testid="stSidebar"] [data-testid="stCaption"] {{
        color: #C9D3E0 !important;
      }}
      div[data-testid="stRadio"] label {{
        padding: 0.25rem 0.15rem;
      }}
      .wdw-hero {{
        padding: 0.15rem 0 1rem;
        margin-bottom: 0.75rem;
        border-bottom: 1px solid {PARCHMENT};
      }}
      .wdw-kicker {{
        color: {ROYAL};
        font-size: 0.78rem;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        font-family: Georgia, serif;
        margin-bottom: 0.35rem;
      }}
      .park-ribbon {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.65rem 1.1rem;
        margin: 0.55rem 0 0.85rem;
        font-size: 0.82rem;
        color: {SLATE};
      }}
      .park-ribbon span {{
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
      }}
      .park-dot {{
        width: 0.65rem;
        height: 0.65rem;
        border-radius: 50%;
        box-shadow: 0 0 0 3px rgba(240,193,74,0.25);
      }}
      .gold-rule {{
        height: 3px;
        width: 148px;
        border-radius: 99px;
        background: linear-gradient(90deg, {GOLD}, {STUDIO_RED}, {LAGOON}, {CANOPY});
        margin-top: 0.55rem;
      }}
      .credit {{ color: {SLATE}; font-size: 0.85rem; }}
      .severity-critical {{
        display: inline-block;
        background: #C8102E;
        color: #fff;
        font-size: 0.72rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 0.12rem 0.45rem;
        border-radius: 99px;
      }}
      .severity-high {{
        display: inline-block;
        background: #E87722;
        color: #fff;
        font-size: 0.72rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 0.12rem 0.45rem;
        border-radius: 99px;
      }}
      .severity-watch {{
        display: inline-block;
        background: {ROYAL};
        color: #fff;
        font-size: 0.72rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 0.12rem 0.45rem;
        border-radius: 99px;
      }}
      .disclaimer {{
        color: {SLATE};
        font-size: 0.8rem;
        margin-top: 2rem;
        padding-top: 0.85rem;
        border-top: 1px solid {PARCHMENT};
      }}
      .main .block-container {{
        position: relative;
        z-index: 1;
        padding-top: 1.35rem !important;
        padding-bottom: 1rem !important;
      }}
      div[data-testid="stDeckGlJsonChart"] {{
        position: fixed !important;
        inset: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        opacity: 0.32;
        pointer-events: none !important;
        z-index: 0 !important;
      }}
      div[data-testid="stDeckGlJsonChart"] canvas {{
        width: 100% !important;
        height: 100vh !important;
      }}
      .element-container:has(div[data-testid="stDeckGlJsonChart"]) {{
        position: fixed !important;
        inset: 0 !important;
        height: 0 !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: visible !important;
        z-index: 0;
      }}
      [data-testid="stDataFrame"] {{
        background: rgba(255,253,248,0.96);
        border: 1px solid {PARCHMENT};
        border-radius: 10px;
      }}
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
    frame = load_hourly(prefer_full=True)
    if frame.empty:
        return frame
    keep = pd.Series(True, index=frame.index)
    if "attraction_key" in frame.columns:
        keep &= frame["attraction_key"].ne("dinosaur")
    if "attraction_name" in frame.columns:
        keep &= ~frame["attraction_name"].str.upper().eq("DINOSAUR")
    return frame.loc[keep].copy()


@st.cache_data(ttl=300, show_spinner=False)
def typical_day_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Catalog + precomputed curves. Switching rides then only filters this table."""
    hourly = historical()
    live, _source = load_live_board()
    catalog = attraction_catalog(hourly, live)
    history = observations_from_hourly(hourly)
    forecast = explode_forecasts(live)
    parts = [frame for frame in (history, forecast) if not frame.empty]
    work = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    curves = typical_day_curve(work, month=now_eastern().month)
    return catalog, curves


@st.cache_data(ttl=600, show_spinner=False)
def wdw_weather() -> dict:
    return fetch_wdw_weather()


@st.cache_data(ttl=300, show_spinner=False)
def scored_headliners() -> pd.DataFrame:
    live, _source = load_live_board()
    if live.empty:
        return pd.DataFrame()
    return expected_wait(live, historical())


def live_attractions(live: pd.DataFrame) -> pd.DataFrame:
    if live is None or live.empty:
        return pd.DataFrame()
    work = live.loc[live["entity_type"] == "ATTRACTION"].copy() if "entity_type" in live.columns else live.copy()
    if "forecast" in work.columns:
        work = work.drop(columns=["forecast"])
    if "standby_wait" in work.columns:
        work["standby_wait"] = pd.to_numeric(work["standby_wait"], errors="coerce")
    return work


def filter_park(frame: pd.DataFrame, park: str) -> pd.DataFrame:
    if frame is None or frame.empty or park == "All parks" or "park_name" not in frame.columns:
        return frame
    return frame.loc[frame["park_name"] == park].copy()


def load_live_board() -> tuple[pd.DataFrame, str]:
    try:
        live = fetch_live()
        return live, "live"
    except ThemeParksError:
        cached = latest_live_frame()
        if cached is not None and not cached.empty:
            return cached, "snapshot"
        return pd.DataFrame(), "unavailable"


def eastern_hour_axis(fig: go.Figure, title: str = "Hour of day (Eastern Time)") -> go.Figure:
    labels = park_day_labels()
    fig.update_xaxes(
        categoryorder="array",
        categoryarray=labels,
        title_text=title,
    )
    return fig


def style_fig(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,253,248,0.55)",
        font=dict(color=NAVY, family='Georgia, "Palatino Linotype", serif'),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            bgcolor="rgba(247,241,230,0.92)",
            bordercolor="rgba(240,193,74,0.35)",
            borderwidth=1,
        ),
        margin=dict(l=40, r=20, t=60, b=40),
        title_font=dict(size=18, color=NAVY, family="Georgia, serif"),
        hoverlabel=dict(bgcolor=CREAM, font_color=NAVY, bordercolor=GOLD),
    )
    fig.update_xaxes(gridcolor="#E8DFD0", zeroline=False, linecolor=PARCHMENT)
    fig.update_yaxes(gridcolor="#E8DFD0", zeroline=False, linecolor=PARCHMENT)
    return fig


def style_ops_bar(fig: go.Figure) -> go.Figure:
    """Bar charts with the title outside the figure so it cannot sit on the legend."""
    fig = style_fig(fig)
    fig.update_layout(
        title_text="",
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.18,
            x=0,
            xanchor="left",
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            title_text="",
        ),
        margin=dict(l=8, r=16, t=8, b=64),
        hoverlabel=dict(
            bgcolor=CREAM,
            font_color=NAVY,
            bordercolor=GOLD,
            font_size=13,
            align="left",
            namelength=-1,
        ),
    )
    return fig


COMPARE_PARK_ORDER = [
    "Magic Kingdom Park",
    "EPCOT",
    "Disney's Hollywood Studios",
    "Disney's Animal Kingdom Theme Park",
]


def typical_day_park_figure(slice_: pd.DataFrame, park: str) -> go.Figure:
    """Full-width park chart with a legend beside the lines."""
    palette = PARK_RIDE_COLORS.get(park, CHART_COLORS)
    fig = px.line(
        slice_,
        x="hour_et",
        y="posted_median",
        color="attraction_name",
        color_discrete_sequence=palette,
        labels={
            "hour_et": "Hour of day (ET)",
            "posted_median": "Wait (minutes)",
            "attraction_name": "Attraction",
        },
    )
    fig.update_traces(line=dict(width=3.5), marker=dict(size=8))
    fig.update_yaxes(rangemode="tozero", title_text="Wait (minutes)", tickfont=dict(size=13))
    eastern_hour_axis(fig, title="Hour of day (ET)")
    fig.update_xaxes(tickfont=dict(size=13), title_font=dict(size=14))
    fig.update_yaxes(title_font=dict(size=14))
    fig = style_fig(fig)
    accent = PARK_COLORS.get(park, NAVY)
    fig.update_layout(
        title=dict(text=park, x=0, xanchor="left", font=dict(size=20, color=accent)),
        height=520,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.01,
            title_text="",
            font=dict(size=13),
            bgcolor="rgba(244,239,230,0.95)",
            borderwidth=0,
            itemclick="toggle",
            itemdoubleclick="toggleothers",
            itemsizing="constant",
        ),
        margin=dict(l=64, r=220, t=64, b=72),
        showlegend=True,
    )
    return fig


def render_radar_background(tile_url: str | None) -> None:
    """Faint RainViewer overlay, cropped to the four Orlando parks — not statewide Florida."""
    layers = []
    if tile_url:
        layers.append(
            pdk.Layer(
                "TileLayer",
                data=tile_url,
                min_zoom=5,
                max_zoom=12,
                tile_size=256,
                opacity=0.55,
            )
        )
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=PARK_POINTS,
            get_position=["lon", "lat"],
            get_radius=220,
            radius_min_pixels=5,
            radius_max_pixels=10,
            get_fill_color=[240, 193, 74, 210],
            get_line_color=[18, 38, 74, 255],
            line_width_min_pixels=1,
            stroked=True,
            filled=True,
        )
    )
    layers.append(
        pdk.Layer(
            "TextLayer",
            data=PARK_POINTS,
            get_position=["lon", "lat"],
            get_text="name",
            get_size=13,
            get_color=[18, 38, 74, 200],
            get_pixel_offset=[0, -16],
        )
    )
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=WDW_LATITUDE,
            longitude=WDW_LONGITUDE,
            zoom=12.15,
            pitch=0,
            bearing=0,
        ),
        map_provider="carto",
        map_style="light",
        tooltip={"text": "{name}"},
    )
    st.pydeck_chart(deck, width="stretch")
    st.markdown(
        f"""
        <style>
          .stApp {{
            background:
              radial-gradient(ellipse at 12% -10%, rgba(240,193,74,0.12), transparent 42%),
              rgba(247,241,230,0.46) !important;
          }}
          [data-testid="stHeader"] {{ background: rgba(247,241,230,0.72) !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def load_weather() -> dict | None:
    try:
        return wdw_weather()
    except WeatherError:
        return None


def render_weather_strip(wx: dict | None) -> None:
    if wx is None:
        st.caption("Weather feed unavailable.")
        return
    current = wx["current"]
    temp = current.get("temp_f")
    rain = wx.get("today_precip_chance")
    wind = current.get("wind_mph")
    summary = " · ".join(
        part
        for part in (
            current.get("condition"),
            None if temp is None else f"{temp:.0f}°F",
            None if rain is None else f"{rain:.0f}% rain today",
            None if wind is None else f"Wind {wind:.0f} mph",
        )
        if part
    )
    st.caption(summary)
    if wx.get("thunderstorm") or (wx.get("alerts") or []):
        st.error(wx.get("implication") or "NWS weather alert in effect.")
        for alert in wx.get("alerts") or []:
            st.warning(f"**NWS {alert['event']}** — {alert['headline']}")
    elif wx.get("implication"):
        st.caption(wx["implication"])
    st.caption(WEATHER_CREDIT)


def page_mission_control(park: str) -> None:
    st.subheader("Mission control")
    st.caption(
        "Park-wide picture this hour: weather holds, downs, waits running hot vs the historical baseline, "
        "and severe standby. Not an official Disney operations system."
    )
    wx = load_weather()
    if wx is not None:
        render_radar_background(wx.get("radar_tiles"))
    live, source = load_live_board()
    if live.empty:
        st.warning("Live ThemeParks.wiki data is unavailable. Park-day and posted-wait pages still work from history.")
        render_weather_strip(wx)
        return
    attractions = filter_park(live_attractions(live), park)
    if attractions.empty:
        st.info("No attractions in this park scope.")
        render_weather_strip(wx)
        return
    if source == "snapshot":
        st.info("Showing the last saved snapshot because a live fetch failed.")
    st.caption(f"{CREDIT} · 5-minute cache · {format_clock(now_eastern())}")

    scored = filter_park(scored_headliners(), park)
    queue = attention_queue(attractions, scored)
    operating = attractions.loc[attractions["status"] == "OPERATING"]
    downs = attractions.loc[attractions["status"] == "DOWN"]
    longest = operating.dropna(subset=["standby_wait"]).nlargest(1, "standby_wait")
    hot = scored.loc[pd.to_numeric(scored.get("delta_vs_expected"), errors="coerce") >= 15] if not scored.empty else pd.DataFrame()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Needs attention", f"{len(queue):,}")
    c2.metric("Down", f"{len(downs):,}")
    c3.metric("Hot vs expected", f"{len(hot):,}")
    if not longest.empty:
        row = longest.iloc[0]
        c4.metric("Longest standby", f"{int(row['standby_wait'])} min", row["entity_name"])
    else:
        c4.metric("Longest standby", "—")

    st.markdown("## Attention queue")
    st.caption("What to handle first this hour. Radar is behind the page, zoomed to the four parks.")
    if queue.empty:
        st.success("No downs, severe standbys, or headliners running 15+ minutes hot vs expected.")
    else:
        shown = queue[
            [
                "severity",
                "park_name",
                "attraction",
                "status",
                "standby_min",
                "vs_expected_min",
            ]
        ].rename(
            columns={
                "severity": "Severity",
                "park_name": "Park",
                "attraction": "Attraction",
                "status": "Status",
                "standby_min": "Standby (min)",
                "vs_expected_min": "Vs expected (min)",
            }
        )
        header_px, row_px = 42, 36
        table_height = header_px + len(shown) * row_px
        st.dataframe(shown, hide_index=True, width="stretch", height=table_height)
        st.caption("Critical = down. High = far above baseline or 90+ minute standby. Watch = elevated but not yet a call-out.")
        st.caption(
            "Expected wait is the TouringPlans historical median for this attraction, hour, and weekday."
        )

    render_weather_strip(wx)

    left, right = st.columns(2)
    with left:
        st.markdown("**Longest standby right now**")
        top = operating.dropna(subset=["standby_wait"]).sort_values("standby_wait", ascending=False).head(12)
        bars = top.sort_values("standby_wait")[["entity_name", "standby_wait", "park_name"]]
        fig = px.bar(
            bars,
            x="standby_wait",
            y="entity_name",
            color="park_name",
            color_discrete_map=PARK_COLORS,
            color_discrete_sequence=CHART_COLORS,
            custom_data=["park_name"],
            labels={"standby_wait": "Standby (min)", "entity_name": "Attraction", "park_name": "Park"},
        )
        fig.update_traces(
            hovertemplate="<b>%{y}</b><br>%{customdata[0]}<br>%{x:.0f} min standby<extra></extra>"
        )
        fig.update_layout(title_text="")
        st.plotly_chart(style_ops_bar(fig), width="stretch")
    with right:
        if scored.empty:
            st.caption("No TouringPlans-mapped headliners in this scope to score against expected wait.")
        else:
            st.markdown("**Headliners vs expected (this hour)**")
            plot = scored.dropna(subset=["standby_wait", "expected_wait"]).copy()
            plot = plot.sort_values("delta_vs_expected")
            parks = plot["park_name"] if "park_name" in plot.columns else pd.Series([""] * len(plot))
            fig2 = go.Figure()
            fig2.add_trace(
                go.Bar(
                    y=plot["entity_name"],
                    x=plot["expected_wait"],
                    name="Expected",
                    orientation="h",
                    marker_color=GOLD,
                    customdata=parks,
                    hovertemplate="%{x:.0f} min<extra></extra>",
                )
            )
            fig2.add_trace(
                go.Bar(
                    y=plot["entity_name"],
                    x=plot["standby_wait"],
                    name="Live standby",
                    orientation="h",
                    marker_color=ROYAL,
                    customdata=parks,
                    hovertemplate="%{x:.0f} min<extra></extra>",
                )
            )
            fig2.update_layout(
                barmode="group",
                title_text="",
                xaxis_title="Wait (min)",
                yaxis_title="",
                hovermode="y unified",
            )
            st.plotly_chart(style_ops_bar(fig2), width="stretch")

    hours = (
        attractions.dropna(subset=["opens_at"])
        .drop_duplicates("park_name")[["park_name", "opens_at", "closes_at"]]
        .sort_values("park_name")
    )
    if not hours.empty:
        hours = hours.copy()
        hours["opens_at"] = format_series(hours["opens_at"])
        hours["closes_at"] = format_series(hours["closes_at"])
        st.markdown("**Park hours (Eastern Time)**")
        st.dataframe(
            hours.rename(columns={"park_name": "Park", "opens_at": "Opens (ET)", "closes_at": "Closes (ET)"}),
            hide_index=True,
            width="stretch",
        )


BOARD_TABLE_HEIGHT = 220
BOARD_CHART_HEIGHT = 360


def ride_board_filters(attractions: pd.DataFrame, headliner_names: set[str]) -> tuple[pd.DataFrame, str, bool]:
    search_col, filter_col = st.columns([4, 1], vertical_alignment="bottom")
    with search_col:
        query = st.text_input("Find an attraction", placeholder="Space Mountain, Flight of Passage…")
    with filter_col:
        headliners_only = st.toggle("Headliners", help="TouringPlans-mapped headliners only")
    view = attractions.copy()
    if headliners_only:
        view = view.loc[view["entity_name"].isin(headliner_names)]
    if query:
        view = view.loc[view["entity_name"].str.contains(query, case=False, na=False)]
    return view, query, headliners_only


def ride_board_table(view: pd.DataFrame, query: str, park: str, headliners_only: bool) -> tuple[str, str] | None:
    keep = [
        col
        for col in (
            "park_name",
            "entity_name",
            "status",
            "standby_wait",
            "return_time_state",
            "return_start",
            "paid_return_state",
        )
        if col in view.columns
    ]
    if park != "All parks":
        keep = [col for col in keep if col != "park_name"]
    table = view[keep].copy()
    if "return_start" in table.columns:
        table["return_start"] = format_series(table["return_start"])
    shown = table.rename(
        columns={
            "park_name": "Park",
            "entity_name": "Attraction",
            "status": "Status",
            "standby_wait": "Standby (min)",
            "return_time_state": "Return",
            "return_start": "Return start (ET)",
            "paid_return_state": "Paid return",
        }
    )
    if "Standby (min)" in shown.columns:
        by = ["Park", "Standby (min)"] if "Park" in shown.columns else ["Standby (min)"]
        ascending = [True, False] if "Park" in shown.columns else [False]
        shown = shown.sort_values(by, ascending=ascending, na_position="last")
    shown = shown.reset_index(drop=True)
    event = st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        height=BOARD_TABLE_HEIGHT,
        on_select="rerun",
        selection_mode="single-row",
        key=f"park-day-ride-board-{query}-{headliners_only}",
    )
    rows = getattr(getattr(event, "selection", None), "rows", None) or []
    if not rows or shown.empty:
        return None
    idx = int(rows[0])
    if idx < 0 or idx >= len(shown):
        return None
    picked = shown.iloc[idx]
    attraction = str(picked["Attraction"])
    park_name = str(picked["Park"]) if "Park" in shown.columns else park
    return park_name, attraction


def typical_day_overlay_figure(
    curve: pd.DataFrame,
    picked: str,
    selected_park: str,
    vs: dict,
    now,
) -> go.Figure:
    accent = PARK_COLORS.get(selected_park, ROYAL)
    fig = go.Figure()
    show_typical = has_typical_series(curve)
    spread = 0.0
    if show_typical:
        spread = float(
            (
                pd.to_numeric(curve["posted_p75"], errors="coerce").fillna(0)
                - pd.to_numeric(curve["posted_p25"], errors="coerce").fillna(0)
            ).max()
        )
    if show_typical and spread >= 1:
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
                fillcolor="rgba(240,193,74,0.28)",
                line=dict(width=0),
                name="Typical 25th–75th",
            )
        )
    if show_typical:
        fig.add_trace(
            go.Scatter(
                x=curve["hour_et"],
                y=curve["posted_median"],
                mode="lines+markers",
                line=dict(color=accent, width=3.5),
                marker=dict(size=7, color=accent),
                name="Typical posted",
            )
        )
        if curve.get("has_actual") is not None and float(curve["has_actual"].fillna(0).max()) > 0:
            fig.add_trace(
                go.Scatter(
                    x=curve["hour_et"],
                    y=curve["actual_median"],
                    mode="lines",
                    line=dict(color=GOLD, width=2.5, dash="dash"),
                    name="Typical actual",
                )
            )
    if has_forecast_series(curve):
        forecast = curve.loc[pd.to_numeric(curve["forecast_wait"], errors="coerce").fillna(0) > 0]
        fig.add_trace(
            go.Scatter(
                x=forecast["hour_et"],
                y=forecast["forecast_wait"],
                mode="lines+markers",
                line=dict(color=LAGOON, width=2.5, dash="dot"),
                marker=dict(size=6, color=LAGOON),
                name="Today's forecast",
                connectgaps=False,
            )
        )
    if vs["live"] is not None:
        fig.add_trace(
            go.Scatter(
                x=hour_et_category(pd.Series([now.hour])),
                y=[vs["live"]],
                mode="markers",
                marker=dict(size=16, color=STUDIO_RED, symbol="diamond", line=dict(width=2, color=NAVY)),
                name="Live standby (now)",
            )
        )
    eastern_hour_axis(fig)
    fig = style_fig(fig)
    highs = []
    for col in ("posted_p75", "posted_median", "actual_median", "forecast_wait"):
        if col in curve.columns:
            highs.append(pd.to_numeric(curve[col], errors="coerce"))
    if vs.get("live") is not None:
        highs.append(pd.Series([vs["live"]]))
    top = pd.concat(highs, ignore_index=True).max(skipna=True)
    ymax = 10.0 if pd.isna(top) else max(float(top) * 1.12, 10.0)
    fig.update_layout(
        title="",
        height=BOARD_CHART_HEIGHT,
        margin=dict(l=42, r=12, t=12, b=56),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.18,
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
            borderwidth=0,
        ),
    )
    fig.update_yaxes(rangemode="tozero", range=[0, ymax], title_text="Wait (min)")
    return fig


def page_typical_day(park: str) -> None:
    st.markdown(
        """
        <style>
          .main [data-testid="stVerticalBlock"] { gap: 0.35rem !important; }
          h2 { font-size: 1.28rem !important; margin: 0 0 0.1rem 0 !important; padding: 0 !important; }
          div[data-testid="stCaptionContainer"] { margin-top: 0 !important; }
          div[data-testid="stCaptionContainer"] p { font-size: 0.78rem !important; }
          div[data-testid="stTextInput"] label { font-size: 0.8rem !important; }
          div[data-testid="stTextInput"] input { padding: 0.28rem 0.55rem !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Park day plan")
    live, source = load_live_board()
    catalog, curves = typical_day_frames()
    headliner_names = set(catalog.loc[catalog["has_touringplans"], "attraction_name"]) if not catalog.empty else set()
    attractions = filter_park(live_attractions(live), park) if not live.empty else pd.DataFrame()
    empty_board = pd.DataFrame(columns=["entity_name", "status"])
    view, query, headliners_only = ride_board_filters(
        attractions if not attractions.empty else empty_board,
        headliner_names,
    )
    if live.empty:
        st.warning("Live ThemeParks.wiki data is unavailable. Typical-day curves still work from history.")
        st.caption(f"{CREDIT}")
        board_pick = None
    else:
        st.caption(f"{len(view):,} attractions · {source} · {CREDIT} · Click a row for the curve below.")
        board_pick = ride_board_table(view, query, park, headliners_only)

    if catalog.empty:
        st.warning("No attractions available for a typical-day curve.")
        return
    parks = sorted(catalog["park_name"].dropna().unique())
    if park != "All parks" and park in parks:
        parks = [park]
    if board_pick:
        selected_park, picked = board_pick
    else:
        selected_park = parks[0]
        pool = catalog.loc[catalog["park_name"] == selected_park]
        if headliners_only:
            pool = pool.loc[pool["has_touringplans"]]
        names = sorted(pool["attraction_name"].unique())
        if not names:
            names = sorted(catalog.loc[catalog["park_name"] == selected_park, "attraction_name"].unique())
        picked = "Seven Dwarfs Mine Train" if "Seven Dwarfs Mine Train" in names else names[0]
    match = catalog.loc[
        (catalog["park_name"] == selected_park) & (catalog["attraction_name"] == picked)
    ]
    curve = curves.loc[(curves["park_name"] == selected_park) & (curves["attraction_name"] == picked)]
    if curve.empty:
        key = str(match.iloc[0]["attraction_key"]) if not match.empty else picked
        curve = empty_typical_day(picked, selected_park, key)
    live_row = pd.DataFrame()
    if not live.empty:
        live_attr = live_attractions(live)
        live_row = live_attr.loc[
            (live_attr["park_name"] == selected_park) & (live_attr["entity_name"] == picked)
        ]
    live_wait = live_row["standby_wait"].iloc[0] if not live_row.empty else None
    now = now_eastern()
    vs = current_vs_typical(curve, live_wait, now.hour)
    typical = "—" if vs["typical"] is None else f"{vs['typical']:.0f} min"
    live_txt = "—" if vs["live"] is None else f"{vs['live']:.0f} min"
    delta = "—" if vs["delta"] is None else f"{vs['delta']:+.0f} min"
    hour_row = curve.loc[pd.to_numeric(curve["hour"], errors="coerce") == now.hour] if not curve.empty else pd.DataFrame()
    if hour_row.empty or "forecast_wait" not in hour_row.columns:
        forecast_txt = "—"
    else:
        forecast_val = pd.to_numeric(hour_row["forecast_wait"].iloc[0], errors="coerce")
        forecast_txt = "—" if pd.isna(forecast_val) or forecast_val <= 0 else f"{forecast_val:.0f} min"
    month_name = now.strftime("%B")
    st.caption(
        f"**{picked}** · {selected_park} · {month_name} typical {typical} · "
        f"Today's forecast {forecast_txt} · Live {live_txt} · Today vs typical {delta}"
    )
    bits = []
    if has_typical_series(curve):
        bits.append(f"Typical posted and the 25–75 band are historical {month_name} hours (all years).")
        if curve.get("has_actual") is not None and float(curve["has_actual"].fillna(0).max()) > 0:
            bits.append("Typical actual is TouringPlans guest-reported waits for those same hours.")
    if has_forecast_series(curve):
        bits.append("Today's forecast is the ThemeParks hourly plan, plotted separately from history.")
    if not has_typical_series(curve) and not has_forecast_series(curve):
        bits.append(
            "No TouringPlans history and no hourly forecast for this attraction — only live standby is shown."
        )
    elif not has_typical_series(curve):
        bits.append("No TouringPlans history for this attraction, so there is no typical posted line or 25–75 band.")
    bits.append("The red diamond is live standby right now.")
    st.caption(" ".join(bits))
    fig = typical_day_overlay_figure(curve, picked, selected_park, vs, now)
    st.plotly_chart(
        fig,
        width="stretch",
        config={"displayModeBar": False},
        key=f"typical-day-{selected_park}-{picked}",
    )

    with st.expander("Compare TouringPlans headliners by park"):
        headliners = set(catalog.loc[catalog["has_touringplans"], "attraction_name"])
        all_curves = curves.loc[curves["attraction_name"].isin(headliners)]
        if park != "All parks":
            all_curves = all_curves.loc[all_curves["park_name"] == park]
        parks_present = [name for name in COMPARE_PARK_ORDER if name in set(all_curves["park_name"])]
        for name in parks_present:
            slice_ = all_curves.loc[all_curves["park_name"] == name]
            st.plotly_chart(
                typical_day_park_figure(slice_, name),
                width="stretch",
                key=f"typical-day-compare-{name}",
            )


def page_posted_vs_actual(hourly: pd.DataFrame, park: str) -> None:
    st.subheader("Posted-wait integrity")
    st.markdown(
        """
The posted wait is a **promise**: stand this long, then you ride. This page checks whether that promise holds.

**Posted** is the number on the sign and in the app. **Actual** is how long a TouringPlans guest reported standing. The **buffer** is posted minus actual.

- A **small positive buffer** is often intentional. Guests beat the sign, trust the next posted wait, and the park avoids missing its own estimate.
- A **large buffer** is where integrity slips. Guests skip a ride that was not as long as advertised, or they stop believing the wait system at all.
- A **negative buffer** is the real miss: the line was longer than the sign. That is the hour to audit.

Use the charts to see **which headliners pad the most** and **which hours the sign is most conservative**.
        """.strip()
    )
    summary = posted_vs_actual(hourly)
    summary = filter_park(summary, park)
    work = hourly
    if park != "All parks":
        work = hourly.loc[hourly["park_name"] == park]
    overall_bias = float(work["posted_minus_actual"].median()) if "posted_minus_actual" in work else float("nan")
    c1, c2, c3 = st.columns(3)
    c1.metric("Headliners", f"{len(summary):,}")
    c2.metric("Median buffer", f"{overall_bias:.1f} min", help="Posted wait minus actual wait. Positive means guests stood less than the sign.")
    c3.metric("Hours with both measures", f"{int(summary['n'].sum()) if not summary.empty else 0:,}")
    st.caption("Buffer = posted − actual. TouringPlans guest reports, not official Disney timing.")

    st.markdown("**Which rides overstate the wait**")
    st.caption("Longer bars mean a bigger typical gap between the sign and what guests actually stood. Headliners often pad more than high-capacity rides.")
    fig = px.bar(
        summary.sort_values("bias_mean"),
        x="bias_mean",
        y="attraction_name",
        color="park_name",
        color_discrete_map=PARK_COLORS,
        color_discrete_sequence=CHART_COLORS,
        labels={"bias_mean": "Mean buffer (min)", "attraction_name": "Attraction", "park_name": "Park"},
    )
    fig = style_fig(fig)
    fig.update_layout(
        title_text="",
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
            title_text="Park",
            bgcolor="rgba(247,241,230,0.95)",
            borderwidth=0,
        ),
        margin=dict(l=40, r=180, t=24, b=40),
        height=520,
    )
    st.plotly_chart(fig, width="stretch")

    st.markdown("**When during the day the sign is most conservative**")
    st.caption("A rising line means the posted wait is padding more in that hour — useful for when to staff merge points and when guests are most likely to distrust the sign.")
    by_hour = (
        work.dropna(subset=["posted_minus_actual"])
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
        labels={"hour_et": "Hour of day (Eastern Time)", "posted_minus_actual": "Median buffer (min)"},
    )
    fig_h.update_traces(line=dict(color=ROYAL, width=3), marker=dict(size=8, color=GOLD))
    fig_h.update_layout(title_text="")
    eastern_hour_axis(fig_h)
    st.plotly_chart(style_fig(fig_h), width="stretch")
    st.caption("Each row is one TouringPlans headliner. Buffer is in minutes; hours is how many attraction-hours had both posted and actual waits.")
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
        ).drop(columns=["attraction_key"], errors="ignore"),
        hide_index=True,
        width="stretch",
    )


def main() -> None:
    clock = format_clock(now_eastern())
    try:
        hourly = historical()
        using_sample = not (hourly is not None and len(hourly) > 20000) and SAMPLE_HOURLY_PARQUET.exists()
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    st.sidebar.markdown(
        f'<p style="color:{GOLD}; letter-spacing:0.14em; font-size:0.72rem; text-transform:uppercase;">Park operations</p>',
        unsafe_allow_html=True,
    )
    park = st.sidebar.selectbox("Park scope", ["All parks", *COMPARE_PARK_ORDER])
    page = st.sidebar.radio(
        "View",
        ["Mission control", "Park day plan", "Posted-wait integrity"],
    )
    st.sidebar.markdown("---")
    st.sidebar.caption(f"Eastern Time {clock}")
    st.sidebar.caption(
        "Not affiliated with The Walt Disney Company. Historical waits: TouringPlans.com. "
        f"Live waits: {CREDIT}."
    )
    if using_sample and not hourly.empty:
        st.sidebar.info("Using the compact sample warehouse. Run `wdw-ingest-history` and `wdw-build` for the full series.")

    if page == "Mission control":
        st.markdown(
            f"""
            <div class="wdw-hero">
              <div class="wdw-kicker">Mission control · {clock}</div>
              <h1 style="margin:0; color:{NAVY}; font-family:Georgia,serif;">Disney World Queue Intelligence</h1>
              <div class="park-ribbon">
                <span><span class="park-dot" style="background:{ROYAL};"></span> Magic Kingdom</span>
                <span><span class="park-dot" style="background:{LAGOON};"></span> EPCOT</span>
                <span><span class="park-dot" style="background:{STUDIO_RED};"></span> Hollywood Studios</span>
                <span><span class="park-dot" style="background:{CANOPY};"></span> Animal Kingdom</span>
              </div>
              <p style="margin:0; color:{SLATE}; max-width:46rem;">
                Mission control for Walt Disney World park operations: weather holds, what is down, what is running hot
                versus a typical hour, and where posted waits diverge from what guests actually stand.
              </p>
              <div class="gold-rule"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        page_mission_control(park)
    elif page == "Park day plan":
        page_typical_day(park)
    else:
        page_posted_vs_actual(hourly, park)

    if page != "Park day plan":
        st.markdown(
            f"<p class='disclaimer'>Independent portfolio project — not an official Disney operations tool. Wait times are third-party observations. {CREDIT} {WEATHER_CREDIT}</p>",
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    main()
