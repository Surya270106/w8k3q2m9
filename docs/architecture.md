# Technical design and implementation notes

## Decision semantics

The evaluation covers **January 2026 decision dates**, not delivery dates. Each decision date maps to the following delivery date: 2 January through 1 February. December warm-up observations may calibrate early decisions but never enter January headline accuracy metrics.

The default decision cutoff is 09:00 Europe/London. It is an assignment assumption, not a market gate-closure claim. Source timestamps are parsed as aware datetimes and normalized to UTC before comparisons.

For each expected hourly delivery start `T`:

1. Derive the delivery date from `T`; the decision date is the previous calendar date in Europe/London.
2. Convert that decision date's configured local cutoff to a UTC instant.
3. Keep WINDFOR records with `startTime == T` and `publishTime <= cutoff`.
4. Select the eligible record with the latest `publishTime`.
5. Compare that hourly forecast with a complete pair of FUELHH WIND actuals at `T` and `T + 30 minutes`.

`startTime` always means delivery time. `publishTime` always means forecast vintage. The source is requested by publication-time bounds to preserve historical vintages.

## Source access, validation and cache

`fetch_actuals` chunks inclusive `settlementDateFrom` / `settlementDateTo` ranges and filters `fuelType=WIND`. `fetch_forecasts` chunks `publishDateTimeFrom` / `publishDateTimeTo` ranges. Requests use explicit timeouts, bounded retries, concurrency limits, strict HTTP status handling and response-shape checks. Pydantic response models validate analysis fields. Unknown `/api/*` routes return JSON 404 responses.

Fetched responses are written as atomic JSON snapshots beneath `DATA_DIR`. Source state is `live`, `cache`, `stale-cache` or `demo`; stale and synthetic states carry warnings. With `ALLOW_DEMO_FALLBACK=false`, an upstream failure returns HTTP 502 rather than silently substituting synthetic observations. The explicit `demo=true` path is deterministic and offline.

Expected hourly intervals are constructed before joins, keeping absent forecasts and incomplete actual pairs in the denominator. FUELHH readings are normalized by `startTime`; when `settlementDate` and `settlementPeriod` exist, they are checked against that timestamp. The exact hourly WINDFOR `startTime` is the join key; targets are not rounded to the hour. Duplicate forecast `(startTime, publishTime)` records use a deterministic canonical tie-break.

The saved January audit records 24 unique WINDFOR target starts and 48 FUELHH starts per delivery day. In the inspected evaluation window, 744 of 744 hourly forecasts matched hourly actuals built from 1,488 distinct half-hour readings. The full raw sample and date-by-date audit are retained in `docs/evidence/`. This is evidence for that inspected source window, not a guarantee about later source responses.

## Calibration and retrospective scoring

For a decision on date `d`, the trailing 14-calendar-day calibration window includes only errors with `deliveryDate < d`. At least five complete days are required; a complete day has all 24 hourly forecasts and paired actuals. The empirical 10th and 90th percentiles of `actual - forecast` form a marginal 80% band around forecasts. The P90 shortfall buffer is the 90th percentile of `max(forecast - actual, 0)` from the same prior-only sample. The current delivery outcome cannot calibrate its own interval.

These are retrospective empirical diagnostics, not formal guarantees. Coverage can drift as regimes change. The over-forecast buffer is not a full procurement quantity: demand, prices, other supply and portfolio positions are not modeled.

Metric conventions:

- `errorMW = forecastMW - actualMW`; positive bias indicates forecast wind exceeded realized wind.
- MAE is mean absolute error; RMSE weights larger misses more strongly.
- WAPE is total absolute error divided by total actual generation.
- MAPE includes only periods with actual generation at least 100 MW; eligible count is returned.
- P90/P95 absolute error are retrospective statistics, separate from the decision-specific over-forecast buffer.
- Forecast horizon is `startTime - selected publishTime` for each chosen vintage.

## Traceability and API

Analysis responses include source labels, fetch time, raw record counts, warnings, a SHA-256 input fingerprint and a cutoff-specific run ID. A run ID ties a result to the data snapshot and decision parameters.

- `GET /api/health`: process liveness; does not depend on Elexon.
- `GET /api/ready`: process readiness; does not establish upstream availability.
- `GET /api/meta`: scope and resolution metadata.
- `GET /api/analysis?month=2026-01&cutoff=09:00&refresh=false&demo=false`: analysis and ledger.
- `GET /docs`: FastAPI schema.

## Deployment topologies and operational limits

- Development: Vite on port 5173 proxies `/api` to FastAPI on port 8000.
- Docker Compose: Nginx on port 8080 serves the frontend and proxies `/api` to a separate API service; a named volume stores snapshots.
- Root `Dockerfile`: builds the frontend and serves its static files from FastAPI in one container. `heroku.yml` describes this topology.

The cache is not a durable shared data store. Ephemeral hosts may lose snapshots and fetch again after restarts. A production service would need persistent snapshot storage, access controls, rate limiting, structured monitoring and incident procedures.
