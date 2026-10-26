# Reviewer video script (maximum 10 minutes)

This is a recording outline, not a claim that a public app or video exists. No public deployment has been verified yet. After deployment, open the app in a private browser window and use only the state and counts shown by that run. The saved January source audit reports 744/744 matched hourly intervals from 1,488/1,488 half-hour actual readings; quote these counts only if the current source badge is `LIVE` and the visible counts agree. Otherwise state the current source label and counts, including cache or demo warnings.

## Part 1: Customer pitch (0:00-4:45)

### 0:00-0:35: Problem and scope

Explain that WindDesk reconstructs which national wind forecast was available at a day-ahead decision cutoff, then evaluates it against later actual generation. It is decision support, not an automated procurement engine.

### 0:35-1:35: Decision replay

Select a decision date and cutoff. Show the next-day delivery date, hourly forecast, publication vintage and actual. Explain that only forecast records published by the cutoff are eligible. Changing the cutoff can select a different vintage.

### 1:35-2:35: Accuracy and coverage

Explain MAE as typical absolute error, RMSE as a metric that emphasizes larger errors, positive bias as over-forecast wind, and WAPE as absolute error relative to total actual generation. State the displayed matched sample, expected periods, missing periods, resolution and source state. Show both half-hour readings behind an hourly mean. Do not describe hourly results as half-hour forecast accuracy.

### 2:35-3:35: Uncertainty

Show the empirical interval and P90 positive over-forecast buffer. Explain that only completed delivery days before the decision can calibrate it, and that it is a retrospective risk signal rather than a procurement quantity.

### 3:35-4:25: Lead time and provenance

Show selected publication timestamps, lead-time diagnostics, fetch time, source state, warnings, run ID and data fingerprint. Explain how these help reviewers distinguish live data from cache and synthetic demo data.

### 4:25-4:45: Summary

Summarize the decision record and its limits: no demand, prices, thermal availability, reserve or portfolio inputs are included.

## Part 2: Technical review (4:45-9:45)

### 4:45-5:30: Architecture

Show the React dashboard, FastAPI service, Compose configuration and root single-container Dockerfile. Explain that Compose is a split Nginx/API topology; the root image runs the built frontend through FastAPI.

### 5:30-6:35: Data contract

Show FUELHH filtered to WIND and queried by settlement-date bounds, and WINDFOR queried by publication-time bounds. Explain timezone-aware comparisons, `startTime` as delivery time, `publishTime` as vintage time, retry/cache behavior and explicit source labels.

### 6:35-7:40: Leakage protection

Show the vintage selection and calibration logic. Emphasize `publishTime <= cutoff` for each hourly delivery target and `deliveryDate < decisionDate` for calibration. January headline metrics exclude the warm-up window.

### 7:40-8:30: Metrics

Review forecast-minus-actual sign convention, MAE/RMSE/WAPE, MAPE eligibility, retrospective absolute-error quantiles and the separate P90 over-forecast buffer. Call out that intervals are empirical diagnostics rather than guarantees.

### 8:30-9:15: Tests and edge cases

Run `python -m pytest -q` and `npm run build --workspace frontend`. Describe checks for distinct :00 and :30 periods, forecast vintages, timezone offsets, duplicates, missing periods, exact cutoff selection and prior-only calibration.

### 9:15-9:45: Limits and handoff

Read the visible source badge, fetch time, matched and missing counts and run ID. State whether Docker and public browser verification have actually passed. Identify missing production features such as authentication, monitoring and persistent shared storage.

Stop before 10 minutes.

## Recording checklist

1. Confirm anonymous access to the verified public repository and deployed app before including their URLs.
2. Capture the actual source badge, fetch timestamp, warnings, run ID, matched count, expected count and missing count.
3. Show decision date, cutoff, delivery date and publication timestamps.
4. Show both half-hour readings and their hourly mean. If an incomplete pair is present, show that it remains missing; never imply missing data was filled.
5. Show calibration sufficiency and explain its prior-only window.
6. Show source/cache/demo behavior, API docs, tests, deployment files and evidence paths.
7. Upload as unlisted only after the recording is under 10 minutes. Submit only verified public URLs.
