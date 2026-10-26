# Video demo script — maximum 10 minutes

Record one unlisted YouTube video with two chapters. Before recording, run the deployed app in an incognito window and check the source badge and resolution note. The verified January 2026 live sample returned source state `live`: 744/744 expected hourly evaluation intervals matched (100%); 0 forecast hours and 0 hourly actuals were missing. All 1,488/1,488 FUELHH half-hours were present and used in pairs. The analysis uses hourly WINDFOR `startTime` targets and the mean of each corresponding pair of 30-minute FUELHH WIND readings. Say that the source feeds have different cadences and show both interval counts. If the badge says **SYNTHETIC DEMO**, say so plainly and do not describe its numbers as real Elexon results.

## Part 1 — Customer pitch (0:00–4:45)

### 0:00–0:35 — Problem and pilot scope

“WindDesk helps the day-ahead procurement team answer two linked questions: what wind forecast was actually available when the purchase decision had to be made, and how reliable were those forecasts historically? This pilot uses only Elexon's national wind actuals and wind forecasts. It is a decision-support view, not an automated procurement engine.”

Point to the January decision window and explain that a decision on 15 January maps to delivery on 16 January.

### 0:35–1:35 — Decision-time view

Select a decision date and the 09:00 Europe/London cutoff. Show the forecast-versus-actual plot and the publication time. Explain that each hourly delivery interval selects the most recent forecast published at or before the cutoff. Change the cutoff to show that the selected vintage and its errors can change.

### 1:35–2:35 — Accuracy metrics

Explain MAE (typical miss), RMSE (larger misses are more heavily penalized), bias (positive means wind was over-forecast), WAPE and the P90 absolute-error statistic. State the matched sample and hourly resolution: 744/744 live hourly intervals paired, built from 1,488 FUELHH half-hours; a missing half-hour would leave its hourly actual unavailable. Accuracy values describe the hourly comparison, not 30-minute forecasts.

### 2:35–3:35 — Decision-time uncertainty

Show the prior-only empirical interval and the rolling P90 over-forecast buffer. Explain the important safeguard: the buffer is calculated from completed delivery days before the decision date; a decision never uses its own later actuals to calibrate its interval. It is a quantified wind-risk signal, not the quantity to buy from the market.

### 3:35–4:25 — Lead-time & auditability

Show MAE by actual forecast lead-time band, publication timestamps, source state, data hash and run ID. Explain how a reviewer can reproduce a result and tell live, cached and demo data apart.

### 4:25–4:45 — Value statement

“The pilot turns a set of forecast and actual files into a traceable view of what was knowable, how much it missed by, and when uncertainty was elevated. A next phase could connect demand and commercial data to quantify procurement exposure, but this pilot intentionally stays within the assigned wind-only scope.”

## Part 2 — Technical lead review (4:45–9:45)

### 4:45–5:30 — Architecture

Show `backend/app/main.py`, `frontend/src/App.tsx`, Docker Compose and the single-container Dockerfile. Explain the split-development and one-container deployment options.

### 5:30–6:35 — Ingestion and forecast vintages

Walk through the separate query contract: FUELHH by inclusive settlement-date bounds with `fuelType=WIND`; WINDFOR by publication time. Explain time-zone-aware UTC comparisons, chunked fetches, bounded retry, disk snapshots, source-state labels and why the newest forecast now is not necessarily the forecast known at yesterday's decision cutoff.

### 6:35–7:40 — Leakage protection

Show `build_decision_rows` and `add_walk_forward_calibration`. Emphasize `publishTime <= cutoff` for each target period and `deliveryDate < decisionDate` for the calibration sample. Demonstrate how the first 14-day warm-up window is excluded from January headline metrics.

### 7:40–8:30 — Numerical definitions

Review the forecast-minus-actual sign convention, MAE/RMSE/WAPE, MAPE eligibility threshold, P90 absolute error versus P90 positive over-forecast buffer, and observed interval coverage. Mention that interval calibration is empirical and not a guarantee.

### 8:30–9:15 — Tests and edge cases

Run `pytest -q`. Call out regressions for the distinct 12:00 and 12:30 targets, multiple publication vintages, timezone-offset normalization, duplicate records, a missing half-hour pair, exact cutoff eligibility, post-cutoff exclusion, missing intervals remaining in the denominator, and preventing a day's own errors entering its calibration band.

### 9:15–9:45 — Known limits and handoff

State whether the live Elexon fetch succeeded in the deployed environment. Identify the exact source badge, fetch timestamp and analysis run ID. Mention that no market prices, demand, thermal constraints, authentication or automated trading actions are included.

Stop by 9:45 to leave room for a short title/end slate and stay under the 10-minute limit.

## Recording run sheet

1. Confirm the visible source badge, fetched-at time, analysis run ID and live-data warning; capture the warning in the recording.
2. Show the selected decision date, following delivery date, UTC cutoff and selected publication timestamps.
3. Show the daily accuracy chart and coverage counters before discussing any metric; state the live sample result only if the visible source badge and counts still agree: 744/744 hourly intervals paired (100%), 0 missing forecast/actual hours, and 1,488/1,488 FUELHH half-hours used. Otherwise read the current sample counts from the app and identify its source state.
4. Show the hourly interval ledger and a row with a missing forecast or incomplete actual pair if one exists; do not imply that missing source observations were filled.
5. Show calibration sample sufficiency and the P90 over-forecast buffer; explain that it is not total procurement quantity.
6. Switch to the technical review screens: source/cache behavior, API docs, backend vintage/calibration functions, tests, Docker configuration and repository layout.
7. Stop the recording before 10:00. Upload as unlisted only after repository and deployment links are verified; do not submit placeholder URLs.
