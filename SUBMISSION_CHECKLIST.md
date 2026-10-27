# WindDesk — submission and release checklist

Updated 27 October 2026.

This checklist distinguishes repository/source review from checks that still need to be run against the exact public release. A page loading successfully does not by itself prove that its API fetched live Elexon data.

## Current public topology

- [x] Public repository: [Surya270106/w8k3q2m9](https://github.com/Surya270106/w8k3q2m9).
- [x] Frontend deployment configured at [Vercel](https://w8k3q2m9.vercel.app/).
- [x] Python API deployment configured at [Render](https://w8k3q2m9.onrender.com/).
- [x] Root `vercel.json` rewrites `/api/*` requests to the Render API.
- [x] Verify unauthenticated HTTP access to the frontend and health, readiness and analysis endpoints on both Vercel and Render (URLs below). The user also confirmed private/incognito access; this records endpoint reachability, not a private-browser visual audit.
- [ ] Recheck live Elexon state after an idle/cold start. The 27 October point-in-time requests returned live data; this was not a cold-start test.

**Deployment disclosure:** this is a split deployment: Vercel hosts the React frontend and Render hosts the FastAPI backend. The README describes this topology. Do not claim the Python API is hosted on Vercel or Heroku.

## Source and method review

The current public `backend/app/main.py` was inspected during this revision:

- [x] Forecast target time comes from WINDFOR `startTime`; forecast vintage comes from `publishTime`.
- [x] For each delivery hour, the selection logic uses the latest forecast whose publication time is at or before the chosen cutoff.
- [x] Actuals are restricted to FUELHH `fuelType=WIND`.
- [x] The hourly actual is the mean of the `:00` and `:30` half-hour readings for that same hour. If either half-hour is missing, the hourly actual remains missing.
- [x] Expected periods stay in the coverage denominator; a missing forecast is not silently dropped.
- [x] Walk-forward calibration filters for completed delivery days strictly earlier than each decision date.
- [x] Earlier warm-up days are used for initial prior-error calibration and excluded from January headline metrics.
- [x] The app describes itself as forecast evaluation/decision support, not a procurement-volume calculator or trading recommendation.

### Explain the warm-up choice in the technical video

WindDesk fetches prior delivery days so that early-January decisions can have an ex-ante calibration history. These rows are used for calibration only, not for the January headline metrics. State this explicitly as a design assumption, because a strict reading of the assignment's date scope may invite a question about fetching earlier days.

## Verification record and remaining engineering checks

| Check | Current evidence | Final release gate |
|---|---|---|
| Backend tests | 53 passed, 0 failed, 0 skipped locally using the bundled Python runtime and the existing temporary verification dependencies; one upstream Starlette/AnyIO deprecation warning. GitHub Actions passed on current commit `b25dcb6`. | [x] Recorded local regression result and successful CI run [40350609025](https://github.com/Surya270106/w8k3q2m9/actions/runs/40350609025). Host `python` was unavailable; tests used the bundled Python runtime. |
| Frontend build | TypeScript and Vite production build passed in GitHub Actions for current commit `b25dcb6`; root Docker build also completed the frontend build. Largest JS chunk 486.73 kB (135.23 kB gzip); no Vite chunk-size advisory. | [x] Build verified in CI and Docker. Host `npm` was unavailable in this shell; npm install emitted the upstream Recharts 2.15.4 deprecation notice. |
| Live Elexon integration | On 27 October 2026, hosted Vercel and Render analysis responses reported `source=live`, `status=live`, 744/744 hourly matches, 0 missing forecast periods, 0 missing actual periods and 1,488/1,488 half-hour readings. | [x] Point-in-time API source and coverage verified. [ ] Cold-start/idle recheck remains outstanding. |
| Docker Compose | `docker compose config`, build, runtime, health/readiness, frontend and analysis checks passed locally on 27 October 2026; live source reported 744/744 hourly and 1,488/1,488 half-hour records. Logs showed no startup/proxy errors or unexpected restarts; stack was stopped. | [x] Compose configuration, build and runtime verified. Named data volume was preserved. |
| Single-container Dockerfile | Root image built and ran locally on 27 October 2026; frontend, health, readiness and analysis returned successfully with live source and complete 744/744 hourly, 1,488/1,488 half-hour coverage. Logs were clean; smoke container was stopped and removed. | [x] Standalone build and runtime verified. |
| Browser QA | Core controls were exercised in a partial manual pass; CSV contents, keyboard accessibility, responsive layouts, and all error states were not fully checked. | [ ] Check the rendered dashboard, source status, chart, one CSV export, and browser console at minimum. |
| README/repository access | Public source and README are published. | [ ] Open the repository in a signed-out/private window and ensure the README and Mermaid diagrams render. |
| Video and form | Not completed as of this checklist revision. | [ ] Record/upload an unlisted video, test its link anonymously, then submit the form. |

## Anonymous deployment checks

These unauthenticated HTTP endpoint checks were performed directly; they do not represent a visual browser walkthrough. The user separately confirmed private/incognito access to the submitted links.

**Vercel**
- [x] [Frontend](https://w8k3q2m9.vercel.app/) (unauthenticated HTTP 200)
- [x] [Health](https://w8k3q2m9.vercel.app/api/health) (unauthenticated HTTP 200)
- [x] [Readiness](https://w8k3q2m9.vercel.app/api/ready) (unauthenticated HTTP 200)
- [x] [January analysis at 09:00 UK cutoff](https://w8k3q2m9.vercel.app/api/analysis?month=2026-01&cutoff=09%3A00) (HTTP 200; live source and complete sample at check time)

**Render**
- [x] [Frontend served by the Render service](https://w8k3q2m9.onrender.com/) (unauthenticated HTTP 200)
- [x] [Health](https://w8k3q2m9.onrender.com/api/health) (unauthenticated HTTP 200)
- [x] [Readiness](https://w8k3q2m9.onrender.com/api/ready) (unauthenticated HTTP 200)
- [x] [January analysis at 09:00 UK cutoff](https://w8k3q2m9.onrender.com/api/analysis?month=2026-01&cutoff=09%3A00) (HTTP 200; live source and complete sample at check time)

For both analysis endpoints, verify the returned source/status identifies real Elexon observations rather than `demo`/synthetic data; expect 744 hourly periods, 744 matched periods when the source is complete, and 1,488 underlying half-hour readings. Check the dashboard's visible source-state label too. A successful health response only proves the process is alive; it does not prove Elexon is reachable.

## Docker checks (only claim success after running them)

From the repository root:

```bash
docker compose up --build
```

Open `http://localhost:8080`, check the dashboard, then verify `/api/health` and `/api/analysis?month=2026-01&cutoff=09%3A00` through port 8080. Stop the stack with `Ctrl+C`.

For the single-container image:

```bash
docker build -t winddesk:local .
docker run --rm -p 8000:8000 -e ALLOW_DEMO_FALLBACK=true winddesk:local
```

Open `http://localhost:8000` and verify health and analysis. Docker was available and both deployment paths were verified on 27 October 2026; see the verification table above.

## Final submission gates

- [ ] Public `main` contains the reviewed README and this reconciled checklist.
- [ ] Backend tests and frontend production build have been rerun on the exact final commit.
- [ ] Vercel frontend and both sets of API endpoints have been checked anonymously after an idle/cold start.
- [ ] Hosted analysis shows live Elexon source status and the expected matched coverage; synthetic/demo data is clearly labelled and is not passed off as live.
- [ ] GitHub README renders in a signed-out/private window.
- [ ] Record two clear sections in one video: customer pitch (5 minutes or less) and technical review (5 minutes or less), with the total under 10 minutes.
- [ ] Upload the video as **unlisted** and open the video URL in a private window without signing in.
- [ ] Submit the application form only once the repo URL, app URL, and video URL work anonymously. Enter and verify your own contact details and resume URL.

Form: https://forms.cloud.microsoft/r/FTX6K2bbnU

## Relevant source and deployment files

- `backend/app/main.py` — ingestion, cutoff/vintage selection, half-hour pairing, calibration, metrics and API endpoints.
- `backend/tests/test_analysis.py` — regression tests.
- `docs/evidence/elexon-january-resolution-audit.json` — saved source-resolution audit.
- `vercel.json` — Vercel frontend build and API rewrite.
- `Dockerfile`, `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` — container options.
