# Pilot deployment runbook

This checklist moves WindDesk from the locally verified source tree to a reproducible pilot. A successful build is not a deployment; complete each stage and save its evidence before sharing a public URL.

## 1. Choose the topology

- **Docker Compose:** two services, Nginx frontend at port 8080 and a separate FastAPI API. The `winddesk-data` named volume stores JSON snapshots.
- **Single-container image:** the root `Dockerfile` builds React assets and serves them from FastAPI. `heroku.yml` describes this image. It is not a Docker Compose deployment. Cache storage is local to the container unless a persistent volume is configured.

## 2. Build and start

From the repository root on a host with Docker Engine and Compose:

```bash
docker compose build --pull
docker compose up -d
docker compose ps
```

To build and run the combined image instead:

```bash
docker build --pull -t winddesk:pilot .
docker run -d --name winddesk-pilot -p 8000:8000 winddesk:pilot
```

For a platform deployment, configure the service to build the root `Dockerfile` and bind the supplied `PORT`. The current Heroku config selects that image; verify the platform still supports the account and deployment path before relying on it.

## 3. Configuration

Review `.env.example` and set only required deployment overrides through the host’s environment configuration. Never put credentials in the image or repository. Important settings:

- `ELEXON_API_BASE`: public BMRS API base URL.
- `ALLOW_DEMO_FALLBACK`: use `true` only when a labelled synthetic fallback is acceptable; set `false` if a source failure must return an error.
- `CACHE_TTL_SECONDS`: memory cache freshness, default 900 seconds.
- `DATA_DIR`: JSON snapshot path. Mount persistent storage at this path if snapshots must survive container replacement.
- `CORS_ORIGINS`: allowed browser origins for a separately hosted frontend. Compose Nginx proxies API calls on the same origin.
- `CALIBRATION_WARMUP_DAYS`, `CALIBRATION_WINDOW_DAYS`, `MIN_CALIBRATION_DAYS`: evaluation and interval configuration; preserve documented defaults unless the change is reviewed.

## 4. Health, readiness and source checks

For Compose, inspect the web endpoint and API service from a browser or command line:

```bash
curl -fsS http://localhost:8080/
curl -fsS http://localhost:8080/api/health
curl -fsS http://localhost:8080/api/ready
curl -fsS 'http://localhost:8080/api/meta'
```

For the combined image, replace port 8080 with the published API port (8000 in the local command above). `/api/health` is liveness and `/api/ready` is process readiness; neither proves Elexon is reachable. Request the analysis and inspect its `source`, `warnings`, `meta.fetchedAt`, record counts, `matchedPeriods`, `expectedDecisionPeriods`, missing-period counts, data fingerprint and run ID. Refresh once to confirm the live-data path. If the result says `cache`, `stale-cache` or `demo`, disclose that source state; do not call it live.

Use `?demo=true` on `/api/analysis` to check the explicit synthetic path. Confirm the UI labels synthetic data clearly. If testing fallback after an upstream failure, do so in a controlled environment and check that the warning identifies demo or stale cache rather than passing it off as live.

## 5. Browser and public-access review

- Load the main page at desktop and narrow/mobile widths; inspect the browser console and network panel for failed requests, CORS errors, React errors and missing static assets.
- Change decision date and cutoff; confirm the visible delivery date, publication vintage and ledger update.
- Confirm the two half-hour actual readings and their hourly mean; check missing source intervals remain empty if present.
- Verify cached, stale and synthetic source states are visually distinguishable.
- Open the public app and repository in a private/incognito window while signed out. This verifies unauthenticated access without relying on an owner session.
- Record the public URL only after the anonymous page load and API request both succeed.

## 6. Logs and rollback

For Compose, use `docker compose logs --tail=200 api web` and `docker compose ps`. For a single container, use `docker logs --tail=200 winddesk-pilot` or the host’s log viewer. Preserve the previous image tag and deployment configuration. If the new build fails health or API checks, restore the last known-good image/configuration, confirm health and analysis behavior again, then investigate from logs. Avoid deleting the named cache volume during rollback unless snapshot loss is intended.

## 7. Operational limits to state

The JSON snapshot cache is not a durable shared database. A restart may lose in-memory freshness; an ephemeral platform may lose local files and refetch Elexon. Health endpoints do not probe upstream data. There is no authentication, commercial procurement workflow, market data, alerting or uptime monitor in this pilot. Treat the first deployment as a monitored evaluation, not a production-ready service.

## Verification record

Deployment status: **not deployed**. Docker runtime and public browser access must be checked on the deployment host. Add the deployed URL, timestamp, source state, coverage and anonymous-access result here only after verifying them.
