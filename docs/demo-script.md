# Reviewer video script (maximum 10 minutes)

This is a recording outline, not a claim that a video exists. The public Vercel frontend and Render backend/API endpoints returned unauthenticated HTTP 200 on 27 October 2026, and the user separately confirmed the submitted links open in a private/incognito window. The hosted analysis APIs reported live Elexon source status with 744/744 hourly matches and 1,488/1,488 half-hour actuals at the time checked. These are point-in-time API checks, not a visual browser audit or idle/cold-start verification. During recording, open the app and quote only the live state and counts actually visible then. The saved January source audit reports 744/744 matched hourly intervals from 1,488/1,488 half-hour actual readings; quote these counts only if the current source badge is `LIVE` and the visible counts agree. Otherwise state the current source label and counts, including cache or demo warnings.

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

Show the React dashboard and FastAPI service. The deployed topology is Vercel for the frontend and Render for the API; Vercel rewrites `/api/*` to Render. The local Compose option uses Nginx on port 8080 to proxy to FastAPI on port 8000; the root single-container image builds React and serves it through FastAPI. Both Docker paths were built and exercised locally on 27 October 2026.

### 5:30-6:35: Data contract

Show FUELHH filtered to WIND and queried by settlement-date bounds, and WINDFOR queried by publication-time bounds. Explain timezone-aware comparisons, `startTime` as delivery time, `publishTime` as vintage time, retry/cache behavior and explicit source labels.

### 6:35-7:40: Leakage protection

Show the vintage selection and calibration logic. Emphasize `publishTime <= cutoff` for each hourly delivery target and `deliveryDate < decisionDate` for calibration. January headline metrics exclude the warm-up window.

### 7:40-8:30: Metrics

Review forecast-minus-actual sign convention, MAE/RMSE/WAPE, MAPE eligibility, retrospective absolute-error quantiles and the separate P90 over-forecast buffer. Call out that intervals are empirical diagnostics rather than guarantees.

### 8:30-9:15: Tests and edge cases

Show the successful CI run for the current source commit and report the local backend result (53 passed, 0 failed, 0 skipped, with one upstream deprecation warning). TypeScript and the Vite production build passed in CI and in the root Docker build. The host shell lacked `npm`, so do not say the host command ran. Describe regression checks for distinct :00 and :30 periods, forecast vintages, timezone offsets, duplicates, missing periods, exact cutoff selection and prior-only calibration.

### 9:15-9:45: Limits and handoff

Read the visible source badge, fetch time, matched and missing counts and run ID. State whether Docker and public browser verification have actually passed. Identify missing production features such as authentication, monitoring and persistent shared storage.

Stop before 10 minutes.

## Recording checklist

1. Confirm anonymous access to the public repository and deployed app before including their URLs; endpoint HTTP checks passed on 27 October, but this was not a visual README/Mermaid browser review.
2. Capture the actual source badge, fetch timestamp, warnings, run ID, matched count, expected count and missing count.
3. Show decision date, cutoff, delivery date and publication timestamps.
4. Show both half-hour readings and their hourly mean. If an incomplete pair is present, show that it remains missing; never imply missing data was filled.
5. Show calibration sufficiency and explain its prior-only window.
6. Show source/cache/demo behavior, API docs, tests, deployment files and evidence paths.
7. Upload as unlisted only after the recording is under 10 minutes. Submit only verified public URLs.
