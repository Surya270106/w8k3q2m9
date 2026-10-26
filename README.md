# WindDesk â€” Decision-time Wind Forecast Intelligence

A full-stack pilot for a UK energy utility evaluating the **national wind forecasts that would have been available at day-ahead purchase decision time**. It combines React, TypeScript, Recharts, FastAPI, and Elexon's public BMRS API.

> **Decision support only.** This pilot measures forecast error and uncertainty. It does not calculate the utility's actual procurement requirement: demand, thermal availability, market prices, and other generation sources are intentionally out of scope.

## Product scope

- **January 2026 purchase decision dates:** 1â€“31 January 2026.
- **Delivery dates evaluated:** 2 Januaryâ€“1 February 2026 (the day after each decision date).
- **Actuals:** Elexon `FUELHH` filtered to `fuelType=WIND`, aligned by `startTime`.
- **Forecasts:** Elexon `WINDFOR`, preserving `publishTime` and `startTime` for vintage selection.
- **Default decision cutoff:** 09:00 Europe/London on Dâˆ’1. This is a configurable assignment assumption, not a claim about a market gate-closure deadline.
- **Source resolution:** FUELHH actuals are 30-minute MW values; WINDFOR stream targets are hourly.
- **Evaluation resolution:** 60 minutes; each hourly FUELHH actual is the mean of both constituent half-hour MW values. A missing half-hour makes that hourly actual unavailable. January has 31 × 24 = **744 expected hourly evaluation intervals** (and 1,488 underlying FUELHH half-hours).

The live feed must be checked in the deployed environment. If it is unavailable, the app clearly identifies deterministic synthetic data instead of implying that those values came from Elexon.

## Capabilities

1. **Decision-time vintage selection.** For every hourly delivery interval, select the latest `WINDFOR` record whose `startTime` is that interval start and whose `publishTime` is at or before the selected cut-off on the preceding decision date. `publishTime` identifies forecast publication, never delivery time. Later vintages are excluded.
2. **Forecast accuracy.** MAE, RMSE, signed bias, WAPE, MAPE (only when actual generation is at least 100 MW), P90/P95 absolute error, over-forecast frequency, error distribution, daily metrics, and hour-of-day diagnostics.
3. **Forecast-horizon diagnostics.** MAE, RMSE and bias are grouped by the selected forecast vintage's actual lead time to delivery.
4. **Walk-forward uncertainty calibration.** A trailing 14-day empirical residual window estimates an 80% interval and P90 *positive over-forecast* buffer. For a decision on day `d`, calibration data must have delivery dates strictly earlier than `d`; the current delivery day and future delivery dates never calibrate their own uncertainty. At least five complete delivery days are required. A day counts toward that minimum only when all 24 hourly forecast/actual pairs are present; each actual pair uses two distinct FUELHH half-hours. Partial days remain in the coverage ledger but do not qualify as complete calibration days. Conflicting duplicate records with the same target and publication timestamp use a stable canonical tie-break, so source page ordering cannot change the analysis.
5. **Auditability.** The API returns source state, record counts, source timestamps, warnings, a data SHA-256 fingerprint, and an analysis run ID.
6. **Data quality accounting.** All expected hourly intervals are generated before joining, so missing forecasts or missing/incomplete actual half-hour pairs reduce coverage instead of disappearing from the denominator.
7. **CSV export.** Download the selected decision-day ledger with forecast/actual values, publication time, error, lead time, and calibrated interval.
8. **Synthetic demo mode.** A UI toggle permits an offline walkthrough. The orange warning is not a decoration: synthetic values must not be used for operational decisions.

## Architecture

```text
React + TypeScript + Recharts
        â”‚ /api/analysis?month=2026-01&cutoff=09:00
        â–¼
FastAPI application
   â”œâ”€â”€ Elexon FUELHH reader â”€â”€ settlement-date window + WIND filter
   â”œâ”€â”€ Elexon WINDFOR reader â”€ publication-time window + retained vintages
   â”œâ”€â”€ local JSON snapshot cache / bounded retries
   â”œâ”€â”€ paired half-hour aggregation & expected hourly calendar
   â”œâ”€â”€ cutoff-aware vintage selector
   â”œâ”€â”€ walk-forward calibration + metrics
   â””â”€â”€ provenance and diagnostics response
        â”‚
        â”œâ”€â”€ Docker Compose: Nginx frontend + API service
        â””â”€â”€ Single Docker image: FastAPI serves the built React app
```

### Important analysis choices

- Error is defined as **forecast âˆ’ actual**. Positive bias means the forecast overestimated wind; this can indicate wind-shortfall risk.
- WAPE is `sum(abs(forecast âˆ’ actual)) / sum(actual)`. MAPE is presented only for periods with actual generation â‰¥ 100 MW to avoid unstable near-zero denominators.
- P90 absolute error is a retrospective magnitude statistic. The decision panel's P90 buffer is different: it is the P90 of `max(forecast âˆ’ actual, 0)` from completed prior delivery days only. It is a risk indicator, **not** a thermal procurement recommendation.
- The nominal 80% interval is empirical, not a guarantee. Its realized coverage is reported in a prequential/walk-forward diagnostic and can differ from 80%. Calibration is pooled across the trailing window rather than conditioned by hour of day or lead-time bucket; the horizon panel is diagnostic, not a conditional probabilistic model. Vintage selection is per hourly target, so if the source has holes the selected delivery day may contain more than one publication vintage. The ledger exposes every selected `publishTime` so the reviewer can inspect this explicitly.
- The warm-up window before January is used only to establish an initial historical calibration sample; it is excluded from January headline metrics.

## Start locally

### Option A â€” Docker Compose (recommended)

Requirements: Docker Desktop / Docker Engine with Compose.

```powershell
docker compose up --build
```

Open the UI at **http://localhost:8080**. The API is available internally to Compose; the health endpoint is proxied at `http://localhost:8080/api/health` and the OpenAPI docs are available on the API container at port 8000 if exposed for local debugging.

### Option B â€” Single container

```powershell
docker build -t winddesk .
docker run --rm -p 8000:8000 -e ALLOW_DEMO_FALLBACK=true winddesk
```

Open **http://localhost:8000** (API docs: `/docs`). This is also the single-container deployment topology used by the included Heroku Docker configuration.

### Option C â€” Local development without Docker

Terminal 1 (backend):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Terminal 2 (frontend):

```powershell
cd frontend
npm ci
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api` to `http://127.0.0.1:8000` by default.

## Tests and quality checks

From the repository root:

```powershell
python -m pip install -r requirements.txt pytest
pytest -q
npm ci
npm run build
```

The tests cover cutoff validation, January date semantics, wind-only filtering, duplicate handling and order independence, exact-cutoff eligibility, post-cutoff exclusion, cutoff sensitivity, missing-period denominators, metric sign conventions, positive over-forecast risk, complete-day calibration minimums, rolling-calibration look-ahead protection, reproducible demo output, and health/readiness endpoints.

The GitHub Actions workflow runs the backend tests and a frontend TypeScript/Vite production build on pushes and pull requests.

## API and configuration

- `GET /api/health` is a liveness check and does not claim that Elexon is reachable.
- `GET /api/ready` reports whether the service and local application configuration are ready.
- `GET /api/meta` returns the evaluation scope and source metadata.
- `GET /api/analysis?month=2026-01&cutoff=09:00&refresh=false&demo=false` returns the validated analysis payload. Set `demo=true` only for an explicitly synthetic walkthrough.
- `GET /docs` serves the FastAPI OpenAPI interface.

Runtime settings include `DATA_DIR`, `CACHE_TTL_SECONDS`, `CALIBRATION_WARMUP_DAYS`, `CALIBRATION_WINDOW_DAYS`, `MIN_CALIBRATION_DAYS`, and `ALLOW_DEMO_FALLBACK`. See `.env.example` and the Live data section below.

## Verification status

- Backend test suite: **29 passed** from a fresh Python 3.12 virtual environment. The `tzdata` dependency supplies the IANA database needed by `zoneinfo` on Windows and minimal images. The only reported warning was an upstream Starlette/AnyIO deprecation warning.
- Frontend TypeScript project build (`tsc -b`) and Vite production build passed. Vite reported a 595 KB JavaScript chunk (168 KB gzip), above its default 500 KB advisory threshold.
- Live Elexon request parameters, response schemas and raw records were checked against the official OpenAPI and endpoint responses. The official OpenAPI schema for WINDFOR stream rows has `startTime`, `publishTime`, and `generation`; it does not include settlement date/period fields. `startTime` identifies delivery; `publishTime` identifies the forecast vintage. Across January, it returned 24 distinct hourly target starts per delivery date. FUELHH returned 48 distinct half-hour targets/day, all of which agreed with `settlementDate` + `settlementPeriod`. A fresh local `/api/analysis` integration request returned HTTP 200 with source state `live`, **744/744 hourly intervals matched (100% coverage)**, 0 missing forecast hours, 0 missing hourly actuals, and 1,488/1,488 underlying January FUELHH half-hours. The actual matched values use paired half-hour means. Incomplete pairs remain missing. Representative raw records and interval counts are saved under `docs/evidence/`.
- Docker is not installed/available in the current shell, so image build and Compose startup remain unverified.
- The connected GitHub account's repository lookup returned 404 and an owner-scoped search returned no `w8k3q2m9`; the name appears available, but GitHub creation remains the authoritative check. No repository was created or pushed. Publication is pending explicit confirmation. No deployment, recording, YouTube upload, or form submission is claimed.

Use `SUBMISSION_CHECKLIST.md` to close these checks in an environment with the required runtimes and account access.

## Live data, cache and demo behaviour

- The app fetches `FUELHH` using inclusive `settlementDateFrom` / `settlementDateTo` date filters and `fuelType=WIND`. Each chunk is bounded to seven dates and normalized against the intended UTC interval window.
- The app fetches `WINDFOR` using `publishDateTimeFrom` / `publishDateTimeTo`, then performs the target-time alignment locally.
- Successful raw source responses are stored under `data/` with fetch metadata and an atomic file replacement. Recent snapshots can be reused; a failed refresh may use a stale snapshot but will label it and show a warning.
- If live fetch fails and no local snapshot exists, `ALLOW_DEMO_FALLBACK=true` allows a clearly labelled synthetic walkthrough. Set it to `false` to return an explicit API error instead.
- To force a refresh, use the UI's **Refresh data** control. The optional **Demo fixture** toggle bypasses the live API intentionally.
- Set `DATA_DIR`, `CACHE_TTL_SECONDS`, `CALIBRATION_WARMUP_DAYS`, `CALIBRATION_WINDOW_DAYS`, and `MIN_CALIBRATION_DAYS` through environment variables if needed.

## Deployment (Heroku, Docker stack)

1. Create a **public** GitHub repository with an anonymous/random repository name, as required by the assignment, and push the source.
2. Install the Heroku CLI, sign in, and create an app name that is available:

   ```powershell
   heroku login
   heroku create <anonymous-app-name>
   heroku stack:set container -a <anonymous-app-name>
   git push heroku main
   heroku open -a <anonymous-app-name>
   ```

3. The included `heroku.yml` uses the root multi-stage `Dockerfile`; the one container serves the React build and FastAPI API on Heroku's `$PORT`.
4. Open `/api/health` and `/docs` on the deployed host. Then open the app in an incognito window and verify source state and data warnings.
5. A deployed service may not have persistent filesystem storage. The app uses its local cache for convenience, not as a durable database. Configure a persistent volume or external object storage before treating it as production infrastructure.

A successful deployment URL is intentionally not hard-coded here: it must be created and verified in the deployer's account.

## Repository layout

```text
.
|-- .dockerignore
|-- .env.example
|-- .github/workflows/ci.yml
|-- .gitignore
|-- backend/
|   |-- app/__init__.py
|   |-- app/main.py
|   |-- requirements.txt
|   |-- Dockerfile
|   `-- tests/test_analysis.py
|-- docs/
|   |-- architecture.md
|   |-- demo-script.md
|   |-- research-notes.md
|   `-- evidence/
|       |-- elexon-january-resolution-audit.json
|       `-- elexon-resolution-samples.json
|-- frontend/
|   |-- src/App.tsx
|   |-- src/main.tsx
|   |-- src/styles.css
|   |-- src/vite-env.d.ts
|   |-- Dockerfile
|   |-- index.html
|   |-- nginx.conf
|   |-- package.json
|   |-- tsconfig.json
|   `-- vite.config.ts
|-- Dockerfile                 # combined frontend + FastAPI image
|-- docker-compose.yml
|-- heroku.yml
|-- package-lock.json
|-- package.json
|-- pytest.ini
|-- README.md
|-- requirements.txt
`-- SUBMISSION_CHECKLIST.md
```

## AI-tool disclosure

AI tools assisted development. **Codex** was used to audit and refine the implementation and documentation. **Claude** was also used where applicable in earlier project work. The live API schema and sampled records were verified against Elexon on 26 October 2026. Deployment behavior remains unverified. Reported live sample counts describe that fetched data window and are not deployment or future-feed guarantees.

## Sources

- [Elexon FUELHH stream documentation](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream)
- [Elexon WINDFOR stream documentation](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream)
- [Elexon official OpenAPI schema](https://data.elexon.co.uk/swagger/v1/swagger.json)
- [REint / GridBricks â€” platform and forecasts](https://reint.ai/)
- [Prognosebuch â€” immutable forecast vintages and transparent backtests](https://github.com/tojacob03/Prognosebuch)
- [Timescale forecast-store â€” versioned forecast data and OpenSTEF benchmark](https://github.com/timescale/forecast-store)
- [Energy price forecasting â€” walk-forward evaluation](https://github.com/soentkeblindow/energy-price-forecast)
