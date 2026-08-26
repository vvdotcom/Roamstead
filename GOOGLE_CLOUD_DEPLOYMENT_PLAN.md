# Roamstead Google Cloud Deployment Plan

## Outcome

Deploy one production demo environment in `us-central1` with:

- `roamstead-web`: public Next.js Cloud Run service.
- `roamstead-api`: public FastAPI + Google ADK Cloud Run service, reached by the web service through `/api` and `/agent-stream` proxies.
- Firestore Native mode: primary durable state for profiles, sessions, revisions, feedback, proposals, 768-dimensional semantic memory, listings, agent runs/events, saves, and Decision Briefs.
- Cloud Storage: private exact-listing photographs served through the API.
- Secret Manager: Gemini credential.
- Pub/Sub: catalog completion/failure events.
- Cloud Run Job + Cloud Scheduler: weekly real-listing refresh.
- Google Maps JavaScript and Geocoding APIs: browser map.
- Optional private GPU Cloud Run service for Gemma only after the hosted-Gemma golden path passes.

The app uses an ephemeral SQLite file only as a per-instance cache. It is not the production source of truth.

## Current readiness

| Area | Status | Evidence or remaining action |
|---|---|---|
| Frontend container | Ready | Next.js standalone output, non-root runtime, Cloud Run port `8080`. |
| API container | Ready | Python 3.12, non-root runtime, writable ephemeral cache, `/health`. |
| Multi-instance state | Ready | Sessions and profiles hydrate from Firestore after process/cache loss. |
| Build contexts | Ready | `.dockerignore` and `.gcloudignore` exclude dependencies, caches, logs, tests, and local secrets. |
| Repository hygiene | Ready | `.gitignore` excludes secrets, databases, downloaded listing assets, logs, build output, and editor files. |
| Cloud bootstrap | Pending external access | Requires a billing-enabled project, authenticated `gcloud`, Firestore location choice, Gemini secret, and restricted Maps key. |
| Production data | Pending first job | Run the catalog job once and verify at least 25 qualified Buy and 25 qualified Rent results before public promotion. |
| Image rights | Manual gate | Confirm permission for public rehosting and preserve source attribution. Do not replace uncertain images with synthetic content. |

“Ready” above means code/configuration has a deployable path; it does not claim that cloud resources already exist.

## Official references

- [Deploying container images to Cloud Run](https://docs.cloud.google.com/run/docs/deploying)
- [Cloud Run service configuration](https://docs.cloud.google.com/run/docs/configuring)
- [Cloud Run health checks](https://docs.cloud.google.com/run/docs/configuring/healthchecks)
- [Create and manage Firestore databases](https://cloud.google.com/firestore/docs/manage-databases)
- [Execute Cloud Run jobs on a schedule](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule)
- [Execute a Cloud Run job and wait](https://docs.cloud.google.com/run/docs/execute/jobs)
- [Cloud Storage least-privilege IAM](https://docs.cloud.google.com/storage/docs/access-control/using-iam-permissions)
- [Cloud Run Secret Manager integration](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

## Phase 0 — local release gate

Run from the repository root:

```powershell
cd apps/api
python -m pip install -e ".[dev]"
python -m pytest -q

cd ../web
npm ci
npm run lint
npm run test
npm run build

cd ../..
docker compose config
docker compose build
docker compose up -d
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000
docker compose down
```

Release only if:

- API tests pass.
- Frontend lint, tests, and production build pass.
- Both containers build and run as non-root users.
- No `.env`, credential JSON, database, listing image cache, log, or `node_modules` directory is present in a Cloud Build upload context.
- The browser golden flow works for Buy and Rent.

## Phase 1 — project bootstrap

Choose the Firestore location once; it cannot be casually changed later. Keep Firestore, Cloud Run, Artifact Registry, Cloud Build, and Storage in compatible nearby locations.

```powershell
$ProjectId = "YOUR_PROJECT_ID"
$Region = "us-central1"

gcloud auth login
gcloud config set project $ProjectId
gcloud projects describe $ProjectId
```

The deployment principal needs permission to enable services, manage IAM/service accounts, build images, deploy Cloud Run services/jobs, and create Artifact Registry, Storage, Pub/Sub, Scheduler, and Secret Manager resources. Use a dedicated deployment identity for repeat deployments; do not give runtime service accounts owner/editor roles.

Create Firestore explicitly in Native mode with deletion protection:

```powershell
gcloud services enable firestore.googleapis.com
gcloud firestore databases create `
  --database="(default)" `
  --location=$Region `
  --type=firestore-native `
  --delete-protection
```

If `(default)` already exists, describe it instead and do not attempt to recreate it:

```powershell
gcloud firestore databases describe --database="(default)"
```

Create `roamstead-gemini-api-key` in Secret Manager and add one enabled version using the Google Cloud console or a secure stdin/file workflow. Never place the Gemini key in Git, a Docker build argument, the deployment script, shell history, or the browser bundle.

Create a separate Google Maps browser key with only:

- Maps JavaScript API.
- Geocoding API.
- HTTP referrers for `http://localhost:3000/*` and the final Cloud Run/custom-domain origin.

The Maps browser key is intentionally visible to browsers; its security boundary is API and referrer restriction.

## Phase 2 — deploy

The deployment script is idempotent for ordinary reruns. It creates resource-scoped application permissions: API reads listing images, the refresh job manages listing-image objects, both publish to the catalog topic, and both read only the Gemini secret they need.

```powershell
$env:ROAMSTEAD_MAPS_BROWSER_API_KEY = "YOUR_RESTRICTED_BROWSER_KEY"
$env:ROAMSTEAD_MAPS_MAP_ID = "YOUR_OPTIONAL_MAP_ID"

.\infra\deploy-cloud-run.ps1 `
  -ProjectId $ProjectId `
  -Region $Region
```

The script must finish with both service URLs. Then add the exact `roamstead-web` URL to the Maps key HTTP-referrer allowlist if it was not known in advance.

Default service limits are intentionally bounded for the hackathon:

| Workload | CPU / memory | Concurrency | Max instances | Timeout |
|---|---:|---:|---:|---:|
| API | 2 vCPU / 2 GiB | 20 | 3 | 300 s |
| Web | 1 vCPU / 512 MiB | 80 | 3 | 300 s |
| Weekly job | 2 vCPU / 4 GiB | one task | one execution | 3600 s |

## Phase 3 — first real-data seed

The API image deliberately contains no local SQLite database or downloaded listing photographs. Seed Firestore and Cloud Storage with the real-data-only job:

```powershell
gcloud run jobs execute roamstead-weekly-catalog `
  --project $ProjectId `
  --region $Region `
  --wait
```

If it fails, inspect the execution and logs. Do not fabricate or insert synthetic replacements:

```powershell
gcloud run jobs executions list `
  --job roamstead-weekly-catalog `
  --project $ProjectId `
  --region $Region

gcloud logging read `
  'resource.type="cloud_run_job" AND resource.labels.job_name="roamstead-weekly-catalog"' `
  --project $ProjectId `
  --limit 100
```

Keep the Scheduler cadence at `0 9 * * 1` in `Etc/UTC`. Provider failure must leave the last verified Firestore/Storage snapshot intact.

## Phase 4 — automated smoke verification

```powershell
.\infra\verify-deployment.ps1 `
  -ProjectId $ProjectId `
  -Region $Region `
  -MinimumListingsPerMode 25
```

This checks:

- public web and API responses;
- Cloud Run deployment mode;
- Google ADK/Gemini execution configuration;
- Gemma critic configuration;
- Firestore-primary mode;
- at least 25 qualified real Batdongsan listings for Buy and Rent;
- no synthetic listing flag/source mismatch;
- Firestore, Pub/Sub, Storage, and scheduled-job resources.

## Phase 5 — golden staging gate

Run three consecutive real Gemini + both Gemma critics + Gemini Embedding Decision Briefs before recording the demo, then 20 fixture-backed browser golden runs. Each proof run must contain `gemini-embedding-001`, `gemma-4-26b-a4b-it`, and `gemma-4-31b-it` in `models_used`, a `READY` memory packet, and successful typed audits from both critics.

Manually prove:

1. Create a clean Buy profile and a clean Rent profile.
2. Hard filters exclude wrong property types, over-budget homes, and insufficient beds/baths.
3. Map clusters and orange Fit Score pins render in Normal and Satellite modes.
4. One adaptive clarification produces a typed proposal.
5. Rejecting a proposal changes nothing; accepting one persists and reorders results.
6. A three-property brief streams distinct specialist timestamps.
7. A successful visual Gemma audit contains model ID, provider, photo count, typed classifications, and property-specific observations.
8. A successful semantic-memory stage contains the embedding model ID, dimension, considered/selected/excluded counts, and no exposed vector values.
9. A successful Gemma 31B audit contains relevant memory IDs, a typed verdict, public findings, duration, and provider.
10. Reload restores profile, feedback, saved items, semantic memory, run trace, and brief from Firestore.
11. Cloud Run logs and Firestore documents visibly prove the same run IDs/model IDs.
10. A stale or failed provider call uses only the last verified snapshot and displays no synthetic property.

## Security and operations gates

- Rotate the Google Maps key previously shared outside Secret Manager, then restrict the replacement key before public launch.
- Keep Gemini only in Secret Manager and grant `secretAccessor` only on that secret.
- Keep the listing-image bucket private; the API reads and streams objects.
- Keep uniform bucket-level access enabled.
- Runtime identities receive no owner/editor roles and no long-lived JSON keys.
- The public API is acceptable for a short hackathon demo only with Cloud Run maximum-instance limits. Before sustained public use, add user authentication, per-user ownership enforcement, rate limiting/Cloud Armor or an API gateway, abuse monitoring, and budget alerts.
- Configure billing budgets and alerts before enabling a private GPU Gemma service.
- Use structured logs without prompts, credentials, hidden reasoning, or personal data.
- Preserve listing source URLs, retrieval timestamps, and image rights records.

## CI/CD after the first manual deployment

Create a Cloud Build trigger for the protected main branch:

1. API tests and frontend lint/test/build.
2. Build immutable images tagged with commit SHA, never only `latest`.
3. Deploy new revisions with no traffic.
4. Run `verify-deployment.ps1` against staging plus the golden browser test.
5. Promote traffic only after all gates pass.
6. Retain the previous known-good revision for rollback.

Do not put the browser Maps key or Gemini key into a repository Cloud Build YAML file. Use Secret Manager and protected build substitutions where appropriate.

## Rollback

List revisions and move traffic back to the last known-good one:

```powershell
gcloud run revisions list --service roamstead-api --project $ProjectId --region $Region
gcloud run revisions list --service roamstead-web --project $ProjectId --region $Region

gcloud run services update-traffic roamstead-api `
  --project $ProjectId --region $Region `
  --to-revisions LAST_GOOD_API_REVISION=100

gcloud run services update-traffic roamstead-web `
  --project $ProjectId --region $Region `
  --to-revisions LAST_GOOD_WEB_REVISION=100
```

Do not roll back Firestore by deleting collections. Application revisions must remain backward-compatible with persisted documents. For a bad catalog refresh, preserve the prior verified snapshot and restore from an exported/versioned snapshot rather than generating substitute data.

## Final promotion checklist

- [ ] Billing and budget alerts configured.
- [ ] Firestore Native `(default)` exists with deletion protection.
- [ ] Gemini secret has an enabled version and narrow access.
- [ ] Maps key rotated and restricted to APIs/referrers.
- [ ] Both Cloud Run services use dedicated runtime identities.
- [ ] First catalog job succeeded.
- [ ] Buy and Rent each return at least 25 qualified real listings.
- [ ] Every displayed listing has USD price, Batdongsan source, timestamp, and Roamstead-served real photo.
- [ ] Adaptive proposal/approval/re-ranking persists across reload.
- [ ] Successful non-degraded Gemma Decision Brief persists across reload.
- [ ] `verify-deployment.ps1` passes.
- [ ] Three consecutive real staging golden runs pass.
- [ ] Twenty fixture-backed browser runs pass.
- [ ] Rollback revisions recorded.
- [ ] Public image redistribution rights reviewed.
