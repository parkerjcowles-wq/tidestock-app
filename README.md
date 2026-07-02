# TideStock

**Bait shop demand-intelligence dashboard.** A SKU-level inventory command center for a coastal bait & tackle shop (Newburyport, MA), pairing classical supply-chain models with live environmental and social demand signals.

Built as a supply-chain portfolio project: it treats a small retailer's reorder decisions the way a planner treats a distribution network — reorder points, service levels, EOQ/newsvendor order quantities, ABC classification, and forecast-accuracy tracking, all driven off real-time data.

## What it does

- **Command Center** — inventory health at a glance: critical/reorder counts, revenue at risk, forecast accuracy, and a ranked buyer action list.
- **Inventory** — days-of-supply vs. lead time, revenue-at-risk exposure, an ABC-filtered reorder queue, a service-level policy panel, and a one-click **draft purchase order** (EOQ for durables, newsvendor for perishables) grouped by category.
- **Demand Signals** — live tides (NOAA), barometric pressure with bite-condition bands, moon phase, species activity, 7-day forecast, tournaments, and web + social fishing chatter.
- **Scenario Simulator** — reweight demand signals or run preset scenarios (tournament weekend, cold front, supplier delay, …) and watch SKU statuses flip.
- **Dave's Brief** — an AI store-manager brief and Q&A grounded in the current numbers, with a deterministic fallback.

## Supply-chain models

| Model | Use |
|---|---|
| Reorder point `= daily demand × lead time + safety stock` | Trigger reorders |
| Safety stock `= z · σ · √LT` | Service-level buffer (z from target service level) |
| EOQ `= √(2DS/H)` | Order quantity for durables |
| Newsvendor (critical ratio) | Order quantity for perishables (live bait) |
| Stockout probability (normal lead-time demand) | Risk scoring |
| ABC classification (Pareto by revenue) | Prioritization |
| WAPE over a moving-average forecast | Forecast-accuracy tracking |

No SciPy — statistics come from the Python standard library (`statistics.NormalDist`).

## Stack

FastAPI · vanilla HTML/CSS/JS frontend (no build step) · ECharts · NOAA + Open-Meteo + Reddit + Exa data feeds · Groq (LLaMA 3) for the AI brief.

## Run locally

```bash
pip install -r requirements.txt
# provide GROQ_API_KEY and EXA_API_KEY in a .env file (see below)
uvicorn main:app --app-dir server --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000`.

The dashboard degrades gracefully if a feed is unavailable, and the AI brief falls back to deterministic recommendations without a Groq key.

### Environment

```
GROQ_API_KEY=your_groq_key
EXA_API_KEY=your_exa_key
```

## Tests

```bash
pytest
```

Model math, analytics, and the API contract are covered; tests are fully mocked and make no live calls.

## Notes

Inventory figures are demo seed data modeled after a real bait-shop workflow — the app is not wired to a live point-of-sale system. Environmental and social signals are live.
