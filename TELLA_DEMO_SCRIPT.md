# Roamstead — Tella Hackathon Demo Script

Target length: **3:05–3:10**  
Primary video: `artifacts/demo-video/roamstead-city-orientations-five-models-continuous-4k.mp4`  
Editable source: `artifacts/demo-video/roamstead-city-orientations-five-models-continuous-1080p.webm`  
Format: **16:9, builder voice, English captions, small camera bubble**  
Primary judging message: **Roamstead is a Collaborative Partner that learns how a person makes a cross-border housing decision, proposes changes instead of silently applying them, and takes only approved due-diligence actions.**

## The first 30 seconds

Do not add a title screen. Show the deployed product immediately.

### 0:00–0:06 — Problem and niche market

**Screen:** Roamstead landing page. Point across Ho Chi Minh City, Bangkok, and Kuala Lumpur, then click **Demo login**.

**Narration:**

> “Americans seeking Southeast Asia’s lower housing costs face foreign-language listings, unfamiliar prices, and evidence they cannot easily verify.”

**Overlay:** `Better value abroad · Harder decisions`

### 0:06–0:15 — City context, then preferences

**Screen:** Demo login opens profile setup directly. Flash the three persisted city orientations, click the narrated HCMC brief, then speed through the profile inputs and click **Show my matches**. Keep the Veo/TTS proof to four edited seconds so Fit Scores are visible by 0:15.

**Narration:**

> “A generated city orientation helps me choose a market; then Roamstead matches real listings to the life and home requirements that matter.”

**Overlay:** `Your life → Hard requirements → Best fit`

### 0:15–0:30 — Working product and real data

**Screen:** Hold on real property photos, USD prices, Fit Scores, fit reasons, and the clustered Google Map while the adaptive analysis begins inline.

**Narration:**

> “In under 20 seconds, I have real cached properties—not synthetic inventory—translated into an explainable shortlist for this family.”

**Overlay:** `Real property · USD · Personalized Fit`

At 30 seconds, the judge should understand the customer, problem, real-data boundary, profile inputs, and working result.

## Full demo

### 0:30–0:50 — One genuinely adaptive question

**Screen:** Show the inline adaptive question. It states that 35 properties meet every hard requirement and compares quiet-neighborhood versus waterfront counterfactuals. Select **Quiet neighborhood**, then pause on the proposal.

**Narration:**

> “This is not a scripted relocation question. Roamstead tests this saved profile against its 35 qualified listings. Quiet would change 14 top-ten positions and the leading match; waterfront would change 10. Gemini turns that measured tradeoff into one useful question.”

**Overlay:** `35 qualified homes · 14 vs 10 ranking changes`

### 0:50–1:03 — Approval-gated learning and reranking

**Screen:** Click **Yes, update my profile** and show the ranking delta.

**Narration:**

> “My answer still changes nothing silently. It creates a specific proposal, explains the predicted impact, and waits. Only after I approve does Roamstead write profile version three and recalculate the ranking.”

**Overlay:** `Analyze → Propose → Approve → Rerank`

### 1:03–1:20 — Real property workflow and firm boundaries

**Screen:** Switch Normal/Satellite map views, open one property, show its real photo and Fit explanation, then select three properties.

**Narration:**

> “Models can reason about tradeoffs, but they cannot override budget, property type, bedrooms, bathrooms, price, or the numeric Fit Score. Inspectable tools own those rules and writes.”

**Overlay:** `Models reason · Tools enforce`

### 1:20–2:05 — Live ADK orchestration

**Screen:** Keep **Building your Decision Brief** full-screen. Follow locked inputs, vector memory, ListingAnalyst, both Gemma critics, CriticJoin, EvidenceVerifier, correction routing, BriefComposer, and database save.

**Narration:**

> “This is one executed ADK workflow, not a timer. Function nodes lock inputs and scores. Gemini Embedding retrieves bounded, profile-isolated decision memory. Gemini analyzes the listings. Two independent Gemma critics start in parallel: one audits real photos while the other checks the analysis against approved memory. A deterministic join and router permit only one correction, and every event is persisted before it streams.”

**Overlay:** `ADK workflow · Parallel critics · Deterministic recovery`

### 2:05–2:30 — Explicit bonus-model proof

**Screen:** Hold on **Model proof**, the completed trace, and the visual- and memory-audit sections.

**Narration:**

> “Each additional Google model has a distinct product job. Gemini Embedding powers 768-dimensional semantic memory. Gemma 4 26B classifies and challenges visual evidence from the exact property photos. Gemma 4 31B checks the brief for conflicts with the user’s approved history. All three model IDs and their successful outputs are persisted here.”

**Overlay sequence:**

1. `Bonus model 1 · gemini-embedding-001 · Semantic memory`
2. `Bonus model 2 · gemma-4-26b-a4b-it · Visual critic`
3. `Bonus model 3 · gemma-4-31b-it · Memory critic`
4. `Additional model · veo-3.1-lite-generate-preview · City orientation`
5. `Additional model · gemini-3.1-flash-tts-preview · Narrated market brief`

Do not describe the models as decorative summaries. Point to the profile-isolated memories, analyzed photo count, audit verdicts, and property-specific missing evidence.

### 2:30–2:55 — Action beyond retrieval

**Screen:** Show the live ADK Decision Watch plan, approval, and immutable evidence revisions.

**Narration:**

> “The partner keeps working after recommendation. ADK chooses only the source, photo, and proximity checks these properties need. Nothing runs until I approve. Missing or contradictory information becomes UNKNOWN; Roamstead never invents a replacement.”

**Overlay:** `Plan → Human approval → Real action`

### 2:55–3:08 — Persisted action

**Screen:** Hold on the completed Decision Watch evidence timeline, then close on the updated HCMC workspace and clustered map.

**Narration:**

> “Roamstead does more than retrieve listings. It preserves approved decisions, executes bounded due diligence, and returns the user to an updated evidence-backed workspace.”

**Overlay:** `Approved actions · Persisted evidence`

### 3:08–3:12 — Close

**Screen:** Finish on the working HCMC property workspace and place the closing positioning line over the final hold.

**Narration:**

> “Roamstead learns with permission, acts with approval, and keeps cross-border housing evidence honest.”

## Required 45-second Google Cloud proof cut

For the final 3:00–3:10 edit, replace the slower final product holds with the sequence in [`CLOUD_PROOF_RECORDING_SCRIPT.md`](CLOUD_PROOF_RECORDING_SCRIPT.md): Cloud Run web, Cloud Run API and Secret Manager binding, the exact Firestore `AgentRun`, its timestamped model events, and the persisted Veo/TTS city media record. Place it at approximately 2:20–3:05, then return to the product for the closing line.

## Tella editing notes

- Use the 3:12 4K continuous take as the timeline base; do not add a logo intro.
- Add the market-problem narration at frame one.
- If you return to the 4:02 source, speed up only the waiting card while Gemini phrases the adaptive question and genuine model/network waits.
- Never imply a failed or degraded run succeeded.
- Keep the camera bubble away from the profile form, adaptive card, workflow status, model-proof row, and audit cards.
- Add captions and manually correct `Roamstead`, `Gemini`, `Gemma`, `ADK`, `Firestore`, and Vietnamese place names.
- The orange circle is the recording cursor.
- Do not say Gemini calculates Fit Scores. Deterministic tools filter and score; models interpret, critique, and orchestrate.
- Do not display a quality-evaluation badge because this take does not show a real passing 20-case evaluation report.
- Judges decide bonus eligibility. Describe the three successful integrations and their jobs; do not claim the award as guaranteed.

## Verified production proof in this take

- Cloud Run web revision: `roamstead-web-00017-5hp`.
- Cloud Run API revision: `roamstead-api-00015-cwq`.
- Profile-first onboarding: Demo login opens directly to destination, Buy/Rent, hard requirements, and Fit Score priorities.
- Adaptive question: generated from 35 qualified listings; predicted 14 quiet-related versus 10 waterfront-related top-ten changes.
- Decision Brief: `COMPLETED`, `degraded=false`, with 20 persisted workflow events.
- Decision Watch: live approval-gated ADK plan and persisted evidence revisions.
- Successful models: `gemini-3.5-flash`, `gemini-embedding-001`, `gemma-4-26b-a4b-it`, `gemma-4-31b-it`, `veo-3.1-lite-generate-preview`, and `gemini-3.1-flash-tts-preview`.
- Current 4K source: 3840×2160 H.264/AAC, 4:37.20, 99,420,944 bytes. The final 3:00–3:10 Tella edit is not yet exported.

## One-sentence positioning

> “Roamstead is a persistent collaborative decision partner that turns messy foreign property data and user feedback into approval-gated profile changes, due-diligence actions, and evidence-backed comparisons.”

## Market evidence behind the opening

- MBO Partners reports **18.5 million American digital nomads in 2025**, approximately 12% of the U.S. workforce: [2025 Digital Nomads Trends Report](https://www.mbopartners.com/state-of-independence/digital-nomads).
- InterNations ranks **Vietnam first for expat personal finance for the fifth consecutive year in 2025**; 89% of surveyed expats were pleased with the general cost of living: [Expat Insider 2025](https://www.internations.org/content-assets/static/dd4b614d816f1b6777b53d4fe8d0e206/Expat-Insider-2025-survey-report_by-InterNations.pdf).
- These are market signals, not a claim that every digital nomad or expat wants to buy property.
