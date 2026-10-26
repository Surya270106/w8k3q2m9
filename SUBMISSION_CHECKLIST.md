# Submission checklist

- [x] Run the backend test suite (29 passed in this workspace).
- [x] Type-check and build the React bundle (`tsc -b`; Vite production build).
- [ ] Docker/Compose check not run: Docker CLI, Docker Desktop executable, and `com.docker.service` are unavailable in this workspace. Build and run `docker compose up --build` on a Docker host before claiming container verification.
- [x] Verify `/api/health`, `/api/ready` and the explicit demo-analysis route in backend tests; separately verify a fresh live `/api/analysis` request returns HTTP 200 and full matched coverage.
- [ ] Recheck visual rendering of the revised resolution/missing-period disclosure in a browser after the current build.
- [x] Verify live Elexon request parameters and responses, including an end-to-end January fetch. Raw evidence confirms hourly WINDFOR targets and 48 FUELHH half-hours/day. The corrected analysis compares hourly forecasts to paired-half-hour means: 744/744 expected hourly intervals matched (100%); 1,488/1,488 January FUELHH half-hours were used; no hourly actuals or periods were filled by duplication. Representative raw fields and per-day counts are in `docs/evidence/elexon-resolution-samples.json` and `docs/evidence/elexon-january-resolution-audit.json`. See `docs/evidence/`.
- [ ] Pending explicit user confirmation: create `Surya270106/w8k3q2m9` as a public repository and push the reviewed source.
- [ ] Deploy the Docker image on Heroku or another permitted public host; verify `/api/health` and the main page.
- [ ] Open the deployed URL and repository in an incognito window.
- [ ] Record the two-part demo (customer pitch + technical review), maximum 10 minutes; upload to YouTube as unlisted.
- [ ] Put only verified public URLs into the Microsoft submission form.
- [ ] Check the README AI-tools disclosure and write down the actual source badge/data snapshot used during recording.

## Microsoft form fields (inspected, not submitted)

The form at https://forms.cloud.microsoft/r/FTX6K2bbnU requires: Name, Phone number, LinkedIn URL, public Google Drive resume link, unlisted YouTube demo link, public app demo URL, GitHub repository URL, and Email ID. The four personal/contact fields require the applicant's own information; this workspace does not contain verified values. The app, repository and video URLs do not exist yet, so the form must remain unsubmitted until those deliverables are published and checked anonymously.
