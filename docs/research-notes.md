# Research notes: product, domain and open-source patterns

Research was used to choose engineering patterns, not to copy another project's source code.

## REint / GridBricks

REint's public product material positions GridBricks around forecasts, energy modelling, optimization, power procurement and decision workflows. The site emphasizes traceability from assumptions to conclusions, comparable scenarios, multi-horizon forecasts and auditable results. For a tightly scoped assessment, the most relevant takeaway is to design the dashboard around a defensible decision record rather than a generic metrics-only page.

Applied here:
- decision date and delivery date are shown together;
- selected forecast publication time is visible;
- cutoff assumptions are editable and documented;
- run metadata identifies the exact data snapshot and cutoff;
- procurement consequences are not overstated beyond the available inputs.

Source: https://reint.ai/ and https://reint.ai/product/forecasts/

## Open-source forecasting/data engineering patterns

### `tojacob03/Prognosebuch`

The project's public README describes forecast outputs committed as immutable files, automatic scoring against subsequent outcomes, misses retained in the track record, and a rolling backtest where each forecast is reconstructed from the information available on its origin date. WindDesk borrows the principle of preserving forecast vintages and avoiding a backtest that silently uses revised or future information; it does not copy its models or data pipeline.

Source: https://github.com/tojacob03/Prognosebuch

### `timescale/forecast-store`

This project connects a versioned forecast data store to an OpenSTEF benchmark and explicitly tracks forecast publication histories/vintages. It reinforces that forecast data should be treated as a time-versioned series rather than a single current value.

Source: https://github.com/timescale/forecast-store

### `soentkeblindow/energy-price-forecast`

The repository describes a reproducible pipeline with chronological features, walk-forward evaluation, calibration, risk diagnostics and checked-in snapshots. This motivated keeping the evaluation reproducible and separating headline accuracy from uncertainty/risk diagnostics.

Source: https://github.com/soentkeblindow/energy-price-forecast

## Elexon data contract

The implementation targets the specified `FUELHH` and `WINDFOR` dataset stream endpoints. FUELHH is fetched by inclusive settlement-date bounds and filtered to `WIND`. WINDFOR is queried by publication-time bounds so records can be filtered to the forecast information set available before a decision cutoff. The live response and official OpenAPI schema were checked on 26 October 2026. WINDFOR provides hourly delivery `startTime`, separate publication `publishTime`, and generation; FUELHH provides half-hour delivery intervals, including `settlementDate` and `settlementPeriod`. The saved raw samples and full January interval audit are in `docs/evidence/`. This verifies the inspected API response, not future or deployment-environment availability.

Sources:
- https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream
- https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream
