# WDW Queue Intelligence

An independent guest-operations analytics project for **Walt Disney World** in Orlando, Florida.

The question is not “what is the wait at Space Mountain.” It is: *if I were briefing a Parks data science or guest-experience team, how do waits behave, where do posted times diverge from what guests actually stand, and what should this wait be right now?*

This is a portfolio project. It is **not affiliated with, endorsed by, or connected to The Walt Disney Company.**

## Problem

Disney parks run on queueing. Capacity, Lightning Lane, early entry, and the posted wait on a sign are all guest-experience decisions. Most public dashboards stop at a live number. Operations work starts one step later:

1. **Posted vs actual wait** — the sign is a communication tool, not a stopwatch. How large is the buffer, and when does it grow?
2. **Shape of a park day** — rope drop, midday peak, evening. Early entry shifts the curve.
3. **Now vs expected** — given hour, weekday, month, and holiday, is this headliner running hot or cold?

## Data

| Layer | Source | What it gives you |
| --- | --- | --- |
| Historical | [TouringPlans.com wait-time datasets](https://touringplans.com/walt-disney-world/crowd-calendar#DataSets) (~14 headliners, posted *and* actual waits, park-day metadata) | Years of structure: hour-of-day, season, Extra Magic Hours / early entry, weather |
| Live | [ThemeParks.wiki API](https://api.themeparks.wiki/) `GET /v1/entity/{parkId}/live` and `/schedule` | All attractions and shows at Magic Kingdom, EPCOT, Hollywood Studios, and Animal Kingdom: standby, downs, Lightning Lane / return times, operating hours |

The two layers are joined **only** for the mapped headliners in [`src/wdw/attraction_map.yml`](src/wdw/attraction_map.yml). The live board is park-wide. Historical models stay on the TouringPlans attraction set. Splash Mountain maps to Tiana's Bayou Adventure; DINOSAUR has no live counterpart.

Live fetches respect ThemeParks.wiki’s cache: refresh no more than once every five minutes. **Powered by ThemeParks.wiki.**

## Method

- Ingest TouringPlans CSVs to an attraction-hour grain (median posted and actual wait).
- Features: attraction, park, hour, weekday, month, weekend, holiday, early entry.
- Baseline model: `HistGradientBoostingRegressor`. Compared against a naive predictor — the historical median for the same attraction, hour, and weekday.
- Live scoring: ThemeParks.wiki standby minus the baseline. The model is an explainable benchmark, **not** a claim to beat Disney’s own wait system.

## Findings

On the compact sample warehouse (and in the same direction as published TouringPlans research on posted vs actual waits):

1. **Posted waits run hotter than actual waits.** The median buffer is on the order of 10–18 minutes and is larger on headliners (Seven Dwarfs Mine Train, Flight of Passage) than on high-capacity rides (Pirates, Spaceship Earth). That is a guest-communication choice: better to beat the sign than miss it.
2. **The day has a shape.** Rope drop is the cheapest hour. Waits climb through late morning, hold through mid-afternoon, and ease after dinner. Early entry days pull demand forward.
3. **A transparent baseline is enough to flag a weird hour.** Attraction and hour dominate permutation importance. On the sample holdout the tree MAE is **3.18 minutes** vs **3.45 minutes** for the naive same-hour/weekday median — a 0.27 minute lift. That modest gap is the honest result. If live standby is 20+ minutes above expected, the park is running hot — not that the model “won.”

Re-run `wdw-ingest-history`, `wdw-build`, and `wdw-train` on the full TouringPlans files to replace the sample with the multi-year series. The notebook and app tell the same three-finding story either way.

## How to run

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Demo with the committed sample (no CSV download required):

```bash
streamlit run app/streamlit_app.py
```

Full historical build:

```bash
wdw-ingest-history          # TouringPlans CSVs via the public data-raw mirror
wdw-ingest-live             # optional ThemeParks.wiki snapshot
wdw-build                   # parquet + DuckDB warehouse
wdw-train                   # baseline model + MAE vs naive
streamlit run app/streamlit_app.py
```

Or open [`notebooks/01_guest_operations_brief.ipynb`](notebooks/01_guest_operations_brief.ipynb).

Official TouringPlans files are updated monthly on the [Crowd Calendar DataSets](https://touringplans.com/walt-disney-world/crowd-calendar#DataSets) page. Drop newer CSVs into `data/raw/touringplans/` using the filenames in `attraction_map.yml` and rebuild.

Tests: `pytest -q`

## Project layout

```
src/wdw/           ingest, warehouse, features, model
app/               Streamlit ops brief
notebooks/         narrative analysis
data/sample/       compact hourly parquet for offline demo
tests/             API flatten, features, warehouse, model
```

## If I had production data at Disney

Next I would add virtual-queue abandon rates, Lightning Lane conversion and return-time tightness, weather at the park (not the airport), special-ticket events, and attraction downtime as a first-class feature. The useful model is not a lower MAE. It is a briefing that tells operations which hour is breaking from the park’s own history.

## Credits and limits

- Historical wait times: TouringPlans.com, used here for data-science / portfolio analysis.
- Live wait times and schedules: ThemeParks.wiki. Powered by ThemeParks.wiki.
- Not official Disney data. Third-party posted waits can lag or miss downtime.
- Large CSVs are gitignored. Do not scrape the Disney app or site.
