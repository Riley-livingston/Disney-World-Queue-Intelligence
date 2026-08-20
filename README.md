# Disney World Queue Intelligence

An independent guest-operations analytics project for **Walt Disney World** in Orlando, Florida.

The question is not “what is the wait at Space Mountain.” It is: *if I were on a park operations radio this hour, what is down, what is running hot versus a typical day, where is Lightning Lane sending people, and where is the posted wait lying to guests?*

This is a portfolio project. It is **not affiliated with, endorsed by, or connected to The Walt Disney Company.**

**Live app:** [disney-world-queue.streamlit.app](https://disney-world-queue.streamlit.app)

## Problem

Disney parks run on queueing. Capacity, Lightning Lane, early entry, and the posted wait on a sign are all guest-experience decisions. Most public dashboards stop at a live number. A shift lead needs the next step:

1. **Mission control** — resort-area radar and forecast, downs, severe standby, headliners running hot vs this hour’s baseline, and Lightning Lane return-time tightness (how far out the next window is, and which hours several attractions stack into).
2. **Park day plan** — live inventory plus typical posted-wait shape with today’s live wait overlaid, for staffing and crowd-flow. Click a ride to load its curve.
3. **Posted-wait integrity** — whether the posted sign matches what guests actually stand, and which rides or hours pad that promise.

## Data

| Layer | Source | What it gives you |
| --- | --- | --- |
| Historical | [TouringPlans.com wait-time datasets](https://touringplans.com/walt-disney-world/crowd-calendar#DataSets) (13 headliners, posted *and* actual waits, park-day metadata) | Years of structure: hour-of-day, season, Extra Magic Hours / early entry, weather |
| Live | [ThemeParks.wiki API](https://api.themeparks.wiki/) `GET /v1/entity/{parkId}/live` and `/schedule` | All attractions and shows at Magic Kingdom, EPCOT, Hollywood Studios, and Animal Kingdom: standby, downs, Lightning Lane / return times, operating hours |

The two layers are joined **only** for the mapped headliners in [`src/wdw/attraction_map.yml`](src/wdw/attraction_map.yml). The live board is park-wide. Historical summaries stay on the TouringPlans attraction set. Splash Mountain maps to Tiana's Bayou Adventure.

Live fetches respect ThemeParks.wiki’s cache: refresh no more than once every five minutes. **Powered by ThemeParks.wiki.**

## Method

- Ingest TouringPlans CSVs to an attraction-hour grain (median posted and actual wait).
- Typical posted, 25–75 band, and typical actual are historical percentiles for the current month.
- Expected wait on Mission control is the historical median for the same attraction, hour, and weekday. Live ThemeParks.wiki standby minus that baseline flags a hot hour. Not a trained model, and not a claim to beat Disney’s own wait system.
- Return-time pressure uses ThemeParks.wiki `RETURN_TIME` and `PAID_RETURN_TIME` states. Lead time is minutes until the posted return start. Stacked hours are three or more attractions in the same park whose windows land in the same Eastern hour. This is the public Lightning Lane window, not Disney’s inventory feed.

## Findings

On the full hourly warehouse (and in the same direction as published TouringPlans research on posted vs actual waits):

1. **Posted waits run hotter than actual waits.** The median buffer is on the order of 10–18 minutes and is larger on headliners (Seven Dwarfs Mine Train, Flight of Passage) than on high-capacity rides (Pirates, Spaceship Earth). That is a guest-communication choice: better to beat the sign than miss it.
2. **The day has a shape.** Rope drop is the cheapest hour. Waits climb through late morning, hold through mid-afternoon, and ease after dinner. Early entry days pull demand forward.
3. **A transparent baseline is enough to flag a weird hour.** If live standby is 20+ minutes above the historical hour/weekday median, the park is running hot.

Re-run `wdw-ingest-history` and `wdw-build` on newer TouringPlans files to refresh `data/processed/hourly.parquet`. The notebook and app tell the same three-finding story from that table.

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
streamlit run app/streamlit_app.py
```

Or open [`notebooks/01_guest_operations_brief.ipynb`](notebooks/01_guest_operations_brief.ipynb).

Official TouringPlans files are updated monthly on the [Crowd Calendar DataSets](https://touringplans.com/walt-disney-world/crowd-calendar#DataSets) page. Drop newer CSVs into `data/raw/touringplans/` using the filenames in `attraction_map.yml` and rebuild.

Tests: `pytest -q`

## Live app (Streamlit Community Cloud)

Public demo: [https://disney-world-queue.streamlit.app](https://disney-world-queue.streamlit.app)

GitHub Pages cannot host this app. Streamlit Community Cloud runs `app/streamlit_app.py` from `main` and loads the committed `data/processed/hourly.parquet` for typical-day and posted-wait pages. Raw TouringPlans CSVs and DuckDB stay gitignored. Pushes to `main` redeploy automatically. Free apps can sleep when idle; the first visit after that is slow.

## Project layout

```
src/wdw/           ingest, warehouse, features, typical-day, expected wait
app/               Streamlit ops brief
notebooks/         narrative analysis
data/processed/    committed hourly.parquet for Cloud and local history
data/sample/       compact hourly parquet fallback
tests/             API flatten, features, warehouse, typical-day
```

## If I had production data at Disney

Next I would add virtual-queue abandon rates, official Lightning Lane conversion, weather at the park (not the airport), special-ticket events, and attraction downtime as a first-class feature. The useful briefing tells operations which hour is breaking from the park’s own history.

## Credits and limits

- Historical wait times: TouringPlans.com, used here for data-science / portfolio analysis.
- Live wait times and schedules: ThemeParks.wiki. Powered by ThemeParks.wiki.
- Not official Disney data. Third-party posted waits can lag or miss downtime.
- Large CSVs are gitignored. Do not scrape the Disney app or site.
