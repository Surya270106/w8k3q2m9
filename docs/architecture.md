# Technical design and implementation notes

## 1. Decision semantics

The assignment asks for **purchase decisions made in January 2026**, not simply delivery periods within January. Therefore the evaluated decision dates are 1–31 January, and each decision maps to the following delivery date: 2 January–1 February. Headline statistics exclude the December warm-up observations.

The cut-off is configurable in Europe/London local time. January is GMT, but timestamps are still parsed and compared as timezone-aware UTC instants to avoid naive/aware comparison bugs and to make the time-zone contract explicit. `tzdata` is declared in backend requirements so `zoneinfo` has IANA data on Windows and minimal Linux images without a system database.

For every expected hourly target time `T`:

1. `D = local_date(T)` is the delivery date.
2. Decision date is `D - 1 day`.
3. Deadline is the selected local cutoff on that decision date, converted to UTC.
4. Only WINDFOR records where `startTime == T` and `publishTime <= deadline` are eligible.
5. Select the eligible record with the greatest `publishTime`.
6. Match it to the WIND-only FUELHH actual at the same target interval.

The forecast feed is queried by **publication time**, not merely target time. This preserves the available publication vintage and allows the cutoff to be changed without re-fetching a new logical dataset window unnecessarily.

## 2. Data access and resilience

`fetch_actuals` chunks inclusive date-only `settlementDateFrom` / `settlementDateTo` windows into at most seven dates and adds `fuelType=WIND`. `fetch_forecasts` chunks the publication-time window into three-day windows with `publishDateTimeFrom` and `publishDateTimeTo`. FUELHH does not accept the generic `from` / `to` parameters used by some other endpoints; the request was corrected after comparing the OpenAPI schema with a live one-day response. Requests use explicit timeouts, a bounded retry policy, concurrency limits, strict status checks and response-shape validation. Analysis responses use Pydantic models to check the API envelope and nested metric, day, and ledger fields. Unknown `/api/*` paths return JSON 404 responses rather than the SPA page.

Raw responses are stored in `DATA_DIR` as atomic JSON snapshots. Cache state is represented as `live`, `cache`, `stale-cache` or `demo`; stale-cache and demo carry warnings. `ALLOW_DEMO_FALLBACK=false` turns an upstream failure into HTTP 502 rather than silently masking it with synthetic data. An explicit demo query parameter enables deterministic UI exploration without making network calls.

All expected hourly evaluation intervals are built first, before forecast and actual joins. FUELHH half-hours are normalized by their `startTime`, checked against `settlementDate` + `settlementPeriod` when those fields are present, then grouped by UTC hour. An hourly MW actual is the arithmetic mean of the distinct `:00` and `:30` MW readings. The join key remains the exact hourly WINDFOR `startTime`; no rounding is applied to forecast targets. Missing forecasts or incomplete actual pairs reduce hourly coverage. The ledger retains every selected publication timestamp. Duplicate `(startTime, publishTime)` forecast records are canonicalized deterministically; raw January evidence showed no duplicate forecast pairs.

The raw January 2026 sample confirmed a source cadence difference. WINDFOR stream rows contain `startTime`, `publishTime`, and `generation`; the stream response does not include `settlementDate` or `settlementPeriod`. Every January delivery date had 24 unique hourly forecast target starts. FUELHH supplied 48 half-hour actual starts per date, and all 2,208 actual records in the 46-day fetched window agreed with their settlement date/period. Across the January evaluation, all 744 hourly targets matched an actual formed from 1,488 distinct half-hour readings, giving 744/744 (100%) hourly paired coverage. Evidence and representative raw rows are preserved in `docs/evidence/`.

## 3. Calibration is separate from retrospective scoring

A common failure mode in forecast dashboards is to calculate the error quantile on all January errors and use it as the decision-day margin. That leaks future outcomes into earlier decisions.

WindDesk calculates decision-specific uncertainty from a trailing 14-calendar-day window of errors with `deliveryDate < decisionDate`. The strict inequality is intentional: at the morning cut-off on day `d`, the delivery day `d` is still in progress and must not calibrate the decision for delivery day `d+1`.

For each decision date:

- Empirical 10th and 90th percentiles of `actual − forecast` produce a marginal 80% prediction band around each selected forecast, provided at least five completed calibration days are available. A day counts only when all 24 hourly intervals have matched forecasts and actuals; partial days do not count toward the minimum.
- The wind-shortfall buffer is the 90th percentile of `max(forecast − actual, 0)` from the same historical sample. It focuses on the direction relevant to wind overestimation rather than treating over- and under-forecast errors as interchangeable.
- After the delivery day, actuals are compared with the interval and the day’s coverage is reported. This gives a walk-forward coverage diagnostic.
- The January headline MAE, RMSE, bias and WAPE always use the January decisions only. December warm-up errors are never included in those headline scores.

These are empirical diagnostics, not formal guarantees. Coverage is marginal, sample-dependent and may drift under regime changes. The P90 buffer is not a full procurement quantity because demand, other supply, reserves, prices and portfolio positions are outside the assignment data scope.

## 4. Metric conventions

- `errorMW = forecastMW − actualMW`.
- Positive bias means forecast wind was higher than realized wind; negative bias means wind was under-forecast.
- MAE is the mean absolute error; RMSE gives larger errors more weight.
- WAPE is total absolute error divided by total actual wind generation.
- MAPE is displayed only for actual values ≥100 MW to avoid unstable near-zero denominators; the API exposes its eligible sample count.
- P90/P95 absolute error are retrospective January metrics. They are not substituted for the decision-specific rolling over-forecast buffer.
- Horizon error bands use `startTime − selected publishTime`, i.e. the selected forecast's actual lead time, not only `delivery-hour + fixed constant`.

## 5. Traceability

The response includes source labels, raw record counts, fetch timestamp, warnings, SHA-256 fingerprint of the data snapshot, and a cutoff-specific analysis run ID. A run ID can be included in a video/demo or issue report to tie a displayed analysis to its input snapshot and cutoff.

## 6. API surface

- `GET /api/health` — lightweight health check; does not require Elexon availability.
- `GET /api/meta` — scope metadata.
- `GET /api/analysis?month=2026-01&cutoff=09:00&refresh=false&demo=false` — full analysis response.
- `GET /docs` — FastAPI OpenAPI docs.

## 7. Deployment topologies

- Development: Vite (`5173`) proxies `/api` to FastAPI (`8000`).
- Docker Compose: Nginx frontend (`8080`) proxies API requests to the separate FastAPI service.
- Single-container: root `Dockerfile` multi-stage-builds the frontend and has FastAPI serve the static bundle. `heroku.yml` configures this topology.

The included local JSON cache is not a durable production data store. On an ephemeral host, each fresh instance may need to fetch the source again. Production hardening would add a persistent object store, data snapshot versioning, request-level rate limiting, structured logs and external uptime/error monitoring.
