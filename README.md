# Roamstead

Roamstead is a collaborative decision partner for cross-border housing. This MVP deliberately focuses on **Ho Chi Minh City** and takes users directly from their relocation preferences to verified properties.

Buy and Rent are first-class modes. Buy uses a $175,000 purchase ceiling; Rent uses a $1,500 monthly ceiling, monthly neighborhood/listing prices, lease-oriented verification language, and a rental-specific action plan.

Property inventory is real-data-only. A resumable weekly builder uses Gemini with grounded Google Search to discover Batdongsan listing pages, then uses Gemini Image Search against each exact page. Gemini translates presentation fields into English. Before a result is accepted, the API requires a numeric source price, a Batdongsan source page, retrievable image bytes, and a photo hash that is not already in the catalog. A separate exact-listing gallery pass can collect additional search-indexed property photographs while rejecting documents, floor plans, maps, graphics, renderings, and duplicates. It also verifies that every asset resolves to Batdongsan's file host and the listing cover's upload session. A listing is publishable once its real source photo is validated. Additional verified photos appear in its gallery when available. Validated photos are downloaded into `data/listing_images` and served through Roamstead `/api/v1/listing-images/...` URLs; the UI never links users to an external photo host. USD is calculated server-side from the reported VND price and is the only price displayed in the UI. Validated batches are upserted incrementally into the local SQLite database at `data/roamstead.db`, so page loads never spend another Gemini request and a partial build survives restarts. Automatic refresh attempts are limited to one per seven-day window, including after provider failures. The catalog targets 100 publishable Buy and 100 publishable Rent properties, including at least 20 each in the Low, Medium, and High bands. Failed search and image calls use bounded retries and backoff within that weekly job. Successful complete refreshes are also mirrored to Firestore when Google Cloud Application Default Credentials are available. The listing API has no synthetic fallback.

Property fit is calculated at request time for the active Decision Profile, never stored as a universal property fact and never assigned by Gemini. USD budget, minimum bedrooms, minimum bathrooms, and the selected Apartment/House categories are hard filters: a property that misses one is excluded. The remaining real listings are ranked from six editable lifestyle preferences: healthcare, remote-work readiness, waterfront access, quiet surroundings, international-school access, and food/daily-needs proximity. Those weights produce an inspectable breakdown and plain-English reasons on every property. Users can reopen **Decision profile** or **Edit profile** at any time; saving immediately recalculates and reorders all listings.

The golden demo visibly proves the core collaboration loop:

1. Choose Buy or Rent and describe the HCMC move.
2. Confirm budget, household space, property category, and lifestyle priorities in the editable Decision Profile.
3. The deterministic counterfactual tool tests possible preference changes against the qualified real catalog. `PreferenceInterpreter` asks exactly one high-information clarification based on the two changes that would alter the current top 10 most.
4. Choose an answer. It creates a typed proposal with predicted rank impact; accept, soften, or reject it. Nothing changes silently.
5. Load the real cached Batdongsan catalog without spending another discovery call and inspect personalized Fit Scores, English presentation, USD prices, local imagery, and source provenance.
6. Reject properties with a concrete reason. Two consistent signals create another typed preference proposal.
7. See the property ranking before and after an approved revision.
8. Select exactly three real properties and create a durable Decision Brief.
9. Watch the database-first stream run `SemanticMemoryTool (Gemini Embedding) -> ListingAnalyst (Gemini) -> VisualEvidenceCritic (Gemma 26B) -> MemoryConsistencyCritic (Gemma 31B) -> EvidenceVerifier (Gemini) -> BriefComposer (Gemini)`, with exactly one bounded correction pass when either critic challenges a claim.
10. Review confirmed, inferred, and unknown claims, retrieved decision memory, both Gemma audits, questions, and next actions. Reload and restore the same brief and completed trace from the database.

## Run locally

In one terminal:

```powershell
cd apps/api
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --port 8000
```

In another:

```powershell
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`.

### Google Maps property view

The results screen includes a Google Map on the right for the complete filtered property set. It geocodes each real listing's saved source address, clusters dense pins, displays the profile Fit Score on each marker, and opens the associated property when selected.

Copy `apps/web/.env.local.example` to `apps/web/.env.local`, then set:

```text
NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=YOUR_RESTRICTED_BROWSER_KEY
NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID=YOUR_OPTIONAL_MAP_ID
```

Enable **Maps JavaScript API** and **Geocoding API**. Because a browser Maps key is intentionally visible to clients, restrict it to those APIs and to `http://localhost:3000/*` plus the production website origin. Restart `npm run dev` after changing the key. Geocoded coordinates are cached only in that browser and expire after 29 days.

To resume a gallery backfill without re-querying completed listings:

```powershell
cd apps/api
python scripts/backfill_galleries.py --mode RENT
python scripts/backfill_galleries.py --mode BUY
```

## Verify

```powershell
cd apps/api
python -m pytest -q

cd ../web
npm run build
```

## Architecture

The production diagram and trust boundaries are in [infra/ARCHITECTURE.md](infra/ARCHITECTURE.md). Google ADK defines a `PartnerCoordinator` graph with `PreferenceInterpreter`, `ListingAnalyst`, `EvidenceVerifier`, and `BriefComposer` specialists. Deterministic tools own counterfactual ranking, database access, profile revisions, source checks, and Fit Scores.

Local development persists listings, profiles, revisions, feedback, proposals, semantic-memory records, saved properties, agent runs/events, and Decision Briefs in `data/roamstead.db`. The browser remembers the active profile ID and restores the same decision state after a reload. Local semantic search uses the same 768-dimensional stored vectors and cosine-distance rules as production; tests may inject deterministic fixture vectors.

In production, set `PERSISTENCE_BACKEND=firestore`. Cloud Run cold instances hydrate state from Firestore; permissioned photos are served from Cloud Storage. The weekly Cloud Run Job writes real catalog snapshots to Firestore/Storage and publishes completion or failure through Pub/Sub. Secret Manager supplies Gemini credentials, and the browser never receives or invokes them.

When `ENABLE_ADK_AGENT=1` and credentials are configured, the adaptive question is phrased by a real Gemini/ADK `PreferenceInterpreter` from deterministic counterfactual results. Decision Brief creation returns HTTP 202 with a durable `QUEUED` run immediately. The browser opens a full progress workspace and then its dedicated Next.js SSE proxy, which starts execution and receives each database-persisted tool/specialist event while the run is active. Event sequence IDs support reconnect and resume without rerunning completed checkpoints.

Gemma 4 is integrated as the multimodal `VisualEvidenceCritic` between Gemini analysis and verification. It receives the deterministic packet, the public analyst claims, and one or two exact-listing photos read from Roamstead's local cache. Its typed audit classifies each photo as interior, exterior, floor plan, document, or unknown; lists only observable features; flags unsupported claims and inadequate evidence; and proposes verification questions. It cannot alter Fit Scores, filters, prices, or preferences. With the existing API key it uses hosted `gemma-4-26b-a4b-it`; set `GEMMA_CRITIC_URL` to use private Cloud Run vLLM. A failure creates a persisted degraded event, and that run cannot be presented as proof of successful Gemma integration. Success is proven by the persisted property-specific audit and model ID, not the health endpoint alone.

Semantic decision memory uses `gemini-embedding-001` with 768-dimensional vectors. Feedback notes, clarification answers, proposal decisions, and approved profile revisions are embedded as retrieval documents. New agent queries use retrieval-query embeddings, are isolated by profile, and retrieve at most five records with cosine distance no greater than `0.30` into a 6,000-character packet. Firestore native vector search is the production path; the deployment script creates the required vector index. Embeddings are never returned by the public memory API and never participate in hard filters, ordering, preference weights, or deterministic Fit Scores. A failed embedding remains `PENDING_EMBEDDING` for backfill while the deterministic workflow continues.

`gemma-4-31b-it` is integrated as `MemoryConsistencyCritic` after the visual audit. It checks Gemini's public analysis against the approved profile and compact semantic-memory packet, identifies conflicts, superseded preferences, unsupported assumptions, and omitted tradeoffs, and may request the same single bounded correction used by the visual critic. It cannot mutate the user profile or evidence. A non-degraded run persists the embedding packet plus successful typed outputs from both Gemma critics and records all model IDs in the live trace and final brief.

## Deploy to Google Cloud

Use [GOOGLE_CLOUD_DEPLOYMENT_PLAN.md](GOOGLE_CLOUD_DEPLOYMENT_PLAN.md) as the authoritative preflight, deployment, verification, and rollback runbook.

Prerequisites are a billing-enabled project, a default Native-mode Firestore database, the Google Cloud CLI, and a Secret Manager secret named `roamstead-gemini-api-key`. Then run:

```powershell
$env:ROAMSTEAD_MAPS_BROWSER_API_KEY="YOUR_RESTRICTED_BROWSER_KEY"
$env:ROAMSTEAD_MAPS_MAP_ID="YOUR_OPTIONAL_MAP_ID"
.\infra\deploy-cloud-run.ps1 -ProjectId YOUR_PROJECT_ID -Region us-central1
```

The script builds and deploys separate API and web Cloud Run services, creates least-privilege service accounts, a private listing-image bucket, Pub/Sub topic, weekly catalog Cloud Run Job, and Cloud Scheduler trigger. It intentionally refuses to choose a Firestore location or place a Gemini key on the command line.

The default deployment uses hosted Gemma 4 through the same Secret Manager API key. For the additional-model Cloud Run proof, deploy a private GPU-backed Gemma service and connect the API identity:

```powershell
.\infra\deploy-gemma-critic.ps1 -ProjectId YOUR_PROJECT_ID -Region us-central1
```

This script follows Google Cloud's official [Gemma 4 with ADK on Cloud Run guide](https://docs.cloud.google.com/run/docs/run-gemma-on-cloud-run), keeps the inference endpoint private, and grants only `roamstead-api` the invoker role. Cloud Run GPU quota and billing are required.

## Trust boundaries

- Rankings are computed from inspectable weights; Gemini never assigns the score.
- A repeated behavior creates a proposal, not a silent profile mutation.
- Listings are accepted only when Gemini returns a grounded Batdongsan source; no synthetic fallback is used.
- Every brief claim retains a status, source URL, observed timestamp, and user-facing explanation.
- Public activity is a concise action trace, not hidden chain-of-thought.
- The Vietnam ownership card links to the official government legal-document portal, shows a check date and confidence, and requires professional verification before a deposit.
