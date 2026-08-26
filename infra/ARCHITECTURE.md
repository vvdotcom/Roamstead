# Roamstead production architecture

![Roamstead Google Cloud production architecture](./roamstead-google-cloud-architecture.svg)

The presentation-ready vector above models the production state. The editable Mermaid source is in [ROAMSTEAD_GCP_ARCHITECTURE_DIAGRAM.md](./ROAMSTEAD_GCP_ARCHITECTURE_DIAGRAM.md), and a 4K PNG export is available as [roamstead-google-cloud-architecture.png](./roamstead-google-cloud-architecture.png).

```text
Browser
  |
  +-- Google Maps JavaScript API + address geocoding
  |     (restricted browser key; 29-day coordinate cache)
  |
  +-- Cloud Run: roamstead-web (Next.js, no secrets)
  |       | /api rewrite
  |       v
  +-- Cloud Run: roamstead-api (FastAPI + Google ADK)
          |
          +-- Adaptive clarification
          |     CounterfactualRankingTool -> PreferenceInterpreter
          |     -> approval-only PreferenceProposal -> ProfileRevisionTool
          |
          +-- PartnerCoordinator ADK workflow
          |     SemanticMemoryTool (gemini-embedding-001, 768d)
          |              | profile-filtered Firestore cosine KNN
          |              v
          |     ListingAnalyst (Gemini 3.5)
          |              |
          |              v
          |     VisualEvidenceCritic (Gemma 4 26B multimodal)
          |              | exact cached photos + typed audit
          |              v
          |     MemoryConsistencyCritic (Gemma 4 31B)
          |              | approved profile + compact memory packet
          |              v
          |     EvidenceVerifier (Gemini 3.5)
          |              |
          |       one bounded correction if CHALLENGE/REVISE
          |              |
          |              v
          |     BriefComposer (Gemini 3.5) -> database write
          |
          +-- deterministic FitScore, evidence, database, and revision tools
          +-- Firestore: profiles, clarifications, revisions, feedback,
          |              semantic_memory + 768d vector index,
          |              proposals, agent runs/events, listings, briefs
          +-- Cloud Storage: permissioned exact-listing photos
          +-- Secret Manager: Gemini credential
          +-- Pub/Sub: refresh completion/failure

Cloud Scheduler (weekly)
  +-- Cloud Run Job: real Batdongsan catalog refresh
          +-- Gemini grounded search and English normalization
          +-- source/photo validation (no synthetic fallback)
          +-- atomic Firestore + Cloud Storage writes
```

SQLite is the local-development adapter and a process-local read cache in Cloud Run. With `PERSISTENCE_BACKEND=firestore`, cold instances hydrate records from Firestore and images from Cloud Storage. Provider failures preserve the latest verified snapshot and its timestamps.

The clarification is selected by measured counterfactual rank impact, not a hard-coded dialogue. Gemini may phrase the data-selected question, but cannot add options or mutate the profile. Decision Brief POST requests return HTTP 202 after persisting a queued run. The connected SSE request starts the workflow and tails durable events, keeping the Cloud Run request active while each specialist result appears live. Every event is written before emission; sequence IDs and phase checkpoints support reconnection without repeating completed model work. The public stream contains only action summaries, typed tool results, evidence states, and recoverable errors. It never exposes hidden reasoning.

Gemma 26B is a product-level visual critic, not a second text summary. It sees only deterministic listing evidence, public Gemini claims, and exact real photos already stored by Roamstead. Gemma 31B independently audits whether that public comparison is consistent with the approved profile and compact retrieved memory. Neither critic may mutate profile state, Fit Scores, filters, prices, or evidence. A model timeout or malformed response degrades the brief explicitly; only successful persisted typed outputs and a READY embedding packet count as model-integration proof.
