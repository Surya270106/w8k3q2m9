# WindDesk — submission and release checklist

Updated 26 October 2026.

This checklist distinguishes repository/source review from checks that still need to be run against the exact public release. A page loading successfully does not by itself prove that its API fetched live Elexon data.

## Current public topology

- [x] Public repository: [Surya270106/w8k3q2m9](https://github.com/Surya270106/w8k3q2m9).
- [x] Frontend deployment configured at [Vercel](https://w8k3q2m9.vercel.app/).
- [x] Python API deployment configured at [Render](https://w8k3q2m9.onrender.com/).
- [x] Root `vercel.json` rewrites `/api/*` requests to the Render API.
- [ ] Verify both deployments and the API anonymously in a private/incognito window (see the exact endpoints below).
- [ ] Confirm the hosted API returns live Elexon data after an idle/cold start, not a synthetic demo fallback.

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
| Backend tests | The README records the latest **reported** local run as 53 passed, 0 failed, 0 skipped. The earlier 33-test count in this checklist was stale. | [ ] Run `python -m pytest -q` from the exact final `main` checkout and record the result. Do not rely on either historical count as proof of the final commit. |
| Frontend build | TypeScript check and Vite production build were previously reported as passing. | [ ] Run `npm run build` from the exact final checkout. |
| Live Elexon integration | A prior local integration run reported 744/744 hourly matches and 1,488/1,488 half-hour readings on 26 October 2026. This is not proof of current hosted behavior. | [ ] Confirm the same coverage and live-source state through the public API after an idle/cold start. |
| Docker Compose | Configuration exists; Docker runtime has not been verified in the recorded environment. | [ ] Run the Compose checks below if Docker is available; otherwise keep the README's “not verified” wording. |
| Single-container Dockerfile | Configuration exists; runtime not verified. | [ ] Build/run the root Dockerfile if Docker is available; otherwise keep “not verified”. |
| Browser QA | Core controls were exercised in a partial manual pass; CSV contents, keyboard accessibility, responsive layouts, and all error states were not fully checked. | [ ] Check the rendered dashboard, source status, chart, one CSV export, and browser console at minimum. |
| README/repository access | Public source and README are published. | [ ] Open the repository in a signed-out/private window and ensure the README and Mermaid diagrams render. |
| Video and form | Not completed as of this checklist revision. | [ ] Record/upload an unlisted video, test its link anonymously, then submit the form. |

## Anonymous deployment checks

Open each URL in a private/incognito browser window.

**Vercel**
- [ ] [Frontend](https://w8k3q2m9.vercel.app/)
- [ ] [Health](https://w8k3q2m9.vercel.app/api/health)
- [ ] [Readiness](https://w8k3q2m9.vercel.app/api/ready)
- [ ] [January analysis at 09:00 UK cutoff](https://w8k3q2m9.vercel.app/api/analysis?month=2026-01&cutoff=09%3A00)

**Render**
- [ ] [Frontend served by the Render service](https://w8k3q2m9.onrender.com/)
- [ ] [Health](https://w8k3q2m9.onrender.com/api/health)
- [ ] [Readiness](https://w8k3q2m9.onrender.com/api/ready)
- [ ] [January analysis at 09:00 UK cutoff](https://w8k3q2m9.onrender.com/api/analysis?month=2026-01&cutoff=09%3A00)

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

Open `http://localhost:8000` and verify health and analysis. If Docker is not available, leave Docker marked unverified in the README.

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
