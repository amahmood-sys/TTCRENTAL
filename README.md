# TTC Subway Delay Tracker 🚇

An interactive Streamlit dashboard for Toronto Transit Commission subway service —
combining a **live status board** with **historical delay analytics** for
Lines 1 (Yonge–University), 2 (Bloor–Danforth), and 4 (Sheppard).

- **🔴 Live Status** — auto-refreshes every 30 s from TTC's official
  GTFS-Realtime service alerts feed; per-line status cards (On Time / Delays /
  No Service) with a system-wide overview banner.
- **📊 History** — 47,831 real delay records (2023–2024) from the City of
  Toronto Open Data portal: monthly trends, hourly distribution, day×hour
  heatmap, top stations, delay causes, and duration distributions.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501

## Refresh the historical dataset

```bash
python data/download_data.py   # rebuilds data/ttc_subway_delays.csv
```

## Deploy

> **Note:** Streamlit is a long-running web server, not a serverless function.
> It **cannot** run on Vercel or other serverless/WSGI platforms (you'll see an
> error about a missing `app`/`application`/`handler` variable). Use one of the
> hosts below, which run a persistent process.

### Option A — Streamlit Community Cloud (easiest, free)
1. Push this repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) → **Sign in with GitHub**.
3. **Create app** → pick this repo, branch `main`, main file `app.py`.
4. **Deploy**. You get a public `*.streamlit.app` URL.

### Option B — Render (free tier)
This repo includes `render.yaml`. On [render.com](https://render.com):
1. **New → Blueprint** → connect this repo.
2. Render reads `render.yaml` and provisions the web service automatically.

### Option C — Railway / Heroku-style
This repo includes a `Procfile`:
```
web: streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
```

## Tech stack
Python · Streamlit · Plotly · Pandas · TTC GTFS-Realtime
