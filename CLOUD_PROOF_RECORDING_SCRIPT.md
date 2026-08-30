# Roamstead — 45-Second Google Cloud and Model Proof

Use this as the final technical segment of a **3:00–3:10** submission video.

Recommended placement: **2:20–3:05**, followed by a five-second return to the product. Keep this sequence continuous. Use zooms and cursor highlights, but do not hide cuts inside fake console animations.

## Prepare these tabs before recording

1. The completed Decision Brief in the deployed Roamstead app.
2. Google Cloud Console → Cloud Run → `roamstead-web`.
3. Google Cloud Console → Cloud Run → `roamstead-api`.
4. Firestore → `agent_runs` → the run shown in the product.
5. Google Cloud Shell with the model-proof command below ready to run.
6. Firestore → `city_orientations` → `ho-chi-minh-city`.

For the current continuous take, the proof run is:

```text
brief-2b96d5eb9ce8
```

Before the final recording, confirm that this ID is still the run visible in the Decision Brief. Never show an unrelated run.

## Exact 45-second shot list

### 2:20–2:27 — Prove the public frontend is Cloud Run

**Screen**

- Show the `roamstead-web` Cloud Run service overview.
- Point to the service name, region `us-central1`, active revision, `100%` traffic, and `.run.app` URL.
- Keep the project selector visibly set to `roamstead-506707`.

**Narration**

> “This is the public Roamstead frontend running on Cloud Run—not localhost—with its active revision serving one hundred percent of traffic.”

**Overlay**

`Cloud Run · Next.js · Public production URL`

### 2:27–2:34 — Prove the separate backend and protected credential

**Screen**

- Switch to `roamstead-api` in Cloud Run.
- Point to its active revision and healthy request activity.
- Briefly open the Variables & Secrets section and show only that `GEMINI_API_KEY` comes from Secret Manager. Never reveal a secret value.

**Narration**

> “A separate FastAPI and ADK service executes the workflow, while Secret Manager supplies the model credential without exposing it to the browser.”

**Overlay**

`Cloud Run · FastAPI + Google ADK · Secret Manager`

### 2:34–2:45 — Tie the app to one durable run

**Screen**

- Open Firestore collection `agent_runs`.
- Select the same run ID shown above.
- Highlight these fields:
  - `status: COMPLETED`
  - `degraded: false`
  - `trace_id`
  - `workflow_version: partner-coordinator-v2`
  - `models_used`

**Narration**

> “This Firestore document is the exact Decision Brief run you just watched. It completed without degraded fallback and records the workflow version, trace ID, and every model that actually participated.”

**Overlay**

`Same run ID · COMPLETED · degraded=false · persisted`

### 2:45–2:57 — Prove actual model execution, not model-name labels

**Screen**

- In Google Cloud Shell, run the command below against the deployed Cloud Run SSE endpoint.
- Show the returned event sequence and point to:
  - `SemanticMemoryTool · gemini-embedding-001 · 817 ms`
  - `ListingAnalyst · gemini-3.5-flash · 15,562 ms`
  - `VisualEvidenceCritic · gemma-4-26b-a4b-it · 10,875 ms`
  - `MemoryConsistencyCritic · gemma-4-31b-it · 3,883 ms`
- Make it visible that both Gemma `SPECIALIST_STARTED` events occur before either completion event.

**Narration**

> “These are separate persisted start and completion events—not UI timers. They show the model, provider, measured duration, and real ordering. Both Gemma critics started before either finished, proving the parallel ADK branch.”

**Overlay**

`Persisted model events · Provider · Duration · Parallel order`

**Cloud Shell command**

```bash
RUN_ID="brief-2b96d5eb9ce8"
API="https://roamstead-api-113080100961.us-central1.run.app"
curl -sN --max-time 15 "$API/api/v1/decision-briefs/$RUN_ID/events?after=0" \
  | grep '^data:' \
  | sed 's/^data: //' \
  | jq -r 'select(.model != null) | [.sequence,.event_type,.actor,.model,.provider,(.duration_ms // "-"),.created_at] | @tsv' \
  | column -t -s $'\t'
```

This reads the durable event stream from the deployed API. It does not rerun or spend another model call.

### 2:57–3:05 — Prove Veo and Gemini TTS produced stored product output

**Screen**

- Open Firestore `city_orientations/ho-chi-minh-city`.
- Highlight:
  - `video_model: veo-3.1-lite-generate-preview`
  - `video_status: READY`
  - `narration_model: gemini-3.1-flash-tts-preview`
  - `narration_status: READY`
  - `generated_at`
  - `property_evidence_eligible: false`
- If readable, show the adjacent Cloud Storage `city_orientations` folder containing the video and audio objects.

**Narration**

> “Veo and Gemini TTS also produced the city orientation you saw. Their outputs are generated once, stored in Cloud Storage, and explicitly barred from property evidence.”

**Overlay**

`Veo + Gemini TTS · READY · Stored once · Not property evidence`

### 3:05–3:10 — Return to the working product

**Screen**

- Return to the completed Decision Brief or HCMC property workspace.
- Hold on the model-proof row and real properties.

**Narration**

> “Roamstead learns with permission, acts with approval, and keeps cross-border housing evidence honest.”

## What proves a real model call

A model name in the UI is not enough. Use this four-part proof chain:

1. **Input/action:** the user starts the real Decision Brief or city narration.
2. **Live execution:** specialist states change at separate timestamps in the product.
3. **Provider record:** the Cloud Run SSE endpoint reads Firestore events containing model, provider, duration, sequence, and run ID.
4. **Persisted output:** the completed brief, Gemma audits, memory packet, video/audio objects, and `degraded=false` state survive reload.

The run currently provides this proof:

| Model | Product job | Persisted execution proof |
|---|---|---|
| `gemini-3.5-flash` | Listing analysis, verification, brief composition | Separate ADK start/completion events and durations |
| `gemini-embedding-001` | 768-dimensional semantic memory retrieval | READY memory event and 817 ms duration |
| `gemma-4-26b-a4b-it` | Visual evidence audit of real listing photos | Property-specific audit and 10,875 ms completion |
| `gemma-4-31b-it` | Memory consistency audit | Typed audit and 3,883 ms completion |
| `veo-3.1-lite-generate-preview` | City orientation video | READY Firestore metadata plus stored MP4 |
| `gemini-3.1-flash-tts-preview` | Narrated city brief | READY Firestore metadata plus stored WAV |

## Do not show or claim

- Do not expose API keys, secret values, access tokens, raw prompts, vectors, or private reasoning.
- Do not use the `/health` configuration response as the main model proof; configuration does not prove execution.
- Do not use BigQuery Agent Analytics as proof in this recording until its production event table actually contains the run.
- Do not claim that Veo or TTS generated property content.
- Do not claim bonus points are guaranteed; say the models are successfully integrated and let judges determine credit.
- Do not rapidly scan every Cloud service. One service revision plus one exact persisted run is more convincing than a console tour.

## Recording technique

- Zoom the browser to approximately 125–150% before opening Firestore fields.
- Collapse irrelevant sidebars.
- Keep the cursor still for one second on every field the narration names.
- Use the same project and run ID throughout the sequence.
- Hide account email, billing details, project IAM members, and unrelated logs.
- Record at 4K so Firestore fields remain readable after YouTube compression.
