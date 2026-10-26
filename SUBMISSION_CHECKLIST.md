# Submission and release checklist

Updated 26 October 2026. This checklist separates verified local work from public milestones that still require a deployment or user-supplied information.

## Local engineering checks

- [x] January 2026 raw Elexon resolution audit preserved under `docs/evidence/`.
- [x] WINDFOR hourly delivery targets use `startTime`; `publishTime` remains the forecast vintage field.
- [x] FUELHH actuals remain half-hourly source values; the hourly result requires a complete pair and displays both readings.
- [x] Full backend suite: 33 passed, zero failed/skipped. TestClient originally hung before app dispatch because Windows asyncio loopback socket-pair initialization was blocked by the sandbox; suite passed with local socket access allowed.
- [x] TypeScript check and Vite production build pass; main JS chunk is 595.24 kB minified / 168.41 kB gzip, with Vite's over-500 kB warning.
- [ ] Docker Compose build/run: not verified if Docker Engine/Compose is unavailable on the current host.
- [ ] Browser rendering and console check: not verified.
- [x] Uvicorn HTTP check: health `ok`, readiness `ready`, unsupported month HTTP 400, and explicit demo analysis schema validated over local HTTP.
- [x] Fresh Elexon API integration: live source, 744/744 hourly matches (100%), no missing forecast/actual hours, and 1,488/1,488 half-hour actual inputs; fetched 2026-10-26T07:58:58Z.
- [ ] Git diff/whitespace checks and local branch/remotes: unavailable because `.git` metadata is absent. A bundled Git executable is available, but this is not a Git checkout. Do not run `git init` or overwrite history to work around this.
- [x] Final local candidate inventory: 34 files. The public `main` tree has 33 blobs; the only added path is `docs/deployment-runbook.md`. Generated builds, dependency folders, caches, `.verify-run`, `.verification-packages`, and local environment files are excluded by ignore rules.
- [x] Secret/environment scan found no credential patterns or applicant contact values in candidate source files; `.env.example` is the only `.env*` file. Markdown UTF-8/mojibake scan is clean.

## Public milestones

- [x] Public source repository exists: [Surya270106/w8k3q2m9](https://github.com/Surya270106/w8k3q2m9).
- [ ] Reconcile this local working tree with the remote commit and publish reviewed local changes through a valid Git checkout. The present workspace has no Git metadata, so it cannot commit or push these local revisions.
- [ ] Deploy a pilot application and verify health, readiness, live-data status, matched coverage and browser API requests.
- [ ] Open repository and app signed out/private browsing session; verify anonymous access.
- [ ] Record and upload an unlisted YouTube demo under 10 minutes.
- [ ] Submit the application form only after repository, app and video URLs are verified and the applicant confirms their own personal contact details.

## Verification record for this revision

| Check | Result |
|---|---|
| Backend test suite | 33 passed, 0 failed, 0 skipped |
| TypeScript and Vite production build | Passed; 595.24 kB main JS chunk warning remains |
| Docker | Not verified in this workspace unless Docker runtime becomes available |
| Uvicorn HTTP and live API integration | Passed: health/readiness, HTTP 400 error behavior, schema-valid demo, and fresh live 744/744 result |
| Browser | Not verified |
| Public deployment | Not deployed |
| Video and form | Not completed |
| Git state | Local `.git` metadata absent; bundled Git executable cannot report a branch or working tree here; no commit or push made |

## Form fields

The Microsoft submission form requests applicant contact information, a resume link, unlisted video URL, public application URL and GitHub URL. Contact details must be supplied and verified by the applicant. Keep the form unsubmitted until the video and application URLs exist and work anonymously.
