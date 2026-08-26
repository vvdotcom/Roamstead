# Roamstead — 4-Minute Winning Demo Script

Target length: **3:45–3:55**, recorded in one continuous take.

Core message: **Roamstead does not just recommend properties. It learns how a person makes a high-stakes cross-border housing decision, asks permission before remembering that lesson, and turns messy evidence into an approval-ready decision.**

## Before recording

- Use a fresh browser profile with no existing Roamstead state.
- Set browser zoom so the Decision Profile, property cards, Partner Activity, and approval dialogs are readable.
- Confirm the public Cloud Run URL works without login.
- Confirm `/health` reports `ADK_GEMINI` and the production persistence backend reports `Firestore`.
- Have two browser tabs ready: Roamstead first, then the Google Cloud Console showing the running Cloud Run services and a Firestore record created by the demo.
- Have the architecture diagram open in a third tab.
- Choose three attractive real listings before recording so you know which cards to compare.
- Run the complete golden path at least three times immediately before recording.
- Do not call the local SQLite build “production,” and do not record the Cloud proof section until the real deployment exists.

## 0:00–0:20 — The hook

**Screen:** Roamstead landing page. Keep the cursor still for the opening sentence.

**Say:**

> “Finding a property abroad is easy. Knowing whether it fits your family—and which claims you can trust—is much harder. Roamstead is a collaborative housing decision agent. It learns how you choose, not just what you click, while keeping every important profile change under your control.”

## 0:20–0:45 — Turn a goal into decision state

**Action:** Select **Buy**, click **Set up my profile**, and briefly point to budget, bedrooms, bathrooms, Apartment/House, international-school access, food access, healthcare, and remote work. Click **Show my matches**.

**Say:**

> “I’m moving to Ho Chi Minh City with a 175-thousand-dollar ceiling. Budget, bedrooms, bathrooms, and property category become hard filters. Lifestyle priorities remain editable weights. Gemini interprets the goal, but it never assigns the Fit Score; deterministic tools do that.”

## 0:45–1:15 — Prove the clarification is adaptive

**Screen:** The adaptive clarification dialog. Point to the qualified-listing count, two options, predicted rank impact, and approval notice.

**Say:**

> “This question is not scripted. Roamstead just tested possible preference changes against every real listing that meets my hard requirements. The Counterfactual Ranking Tool selected the unresolved tradeoff with the greatest top-ten impact, and Gemini’s Preference Interpreter phrased one concise question.”

**Action:** Choose the first meaningful option. When the proposal appears, pause on the old and proposed weights, then click **Yes, update my profile**.

**Say:**

> “My answer creates a proposal—not a silent mutation. Only after I approve it does Roamstead write a new profile revision and recompute the ranking.”

## 1:15–1:40 — Prove real, messy data became useful

**Screen:** Results. Slowly move across photos, USD prices, Fit Scores, school/food proximity, and local image URLs. Open one attractive property briefly, then close it.

**Say:**

> “These are real Vietnamese listings, not generated inventory. A weekly Gemini workflow discovers source pages, translates Vietnamese presentation fields into English, normalizes VND to USD, validates images, and saves a verified snapshot. Page loads query the database, so Gemini is not repeatedly called for the same catalog.”

## 1:40–2:15 — The Collaborative Partner moment

**Action:** On two listings, select **Not for me → Too expensive**. Pause when the pattern proposal appears. Approve it, then point to **Why your ranking changed**, the old/new score or rank, and **Hard constraints unchanged**.

**Say:**

> “Now I reject two otherwise strong matches for the same reason. Roamstead records immutable feedback, detects the pattern, and asks whether budget sensitivity should matter more. I approve it, and the ranking visibly changes. Notice that the explanation comes from structured score deltas, while every locked requirement remains unchanged.”

## 2:15–3:05 — Show genuine ADK orchestration

**Action:** Select **Compare** on exactly three properties and click **Build Decision Brief**. The full live workspace opens immediately. Pause on each changing stage card: deterministic lock, Listing Analyst, Gemma Visual Evidence Critic, Evidence Verifier, optional correction, Brief Composer, and database save.

**Say:**

> “A recommendation is not enough for a cross-border purchase, so Roamstead completes the workflow live. Google ADK routes three Gemini specialists, but Gemma 4 performs an independent visual audit in the middle. It sees the exact locally cached photos, classifies interiors, exteriors, floor plans, or documents, and challenges claims the photos cannot support. Every result is saved before this screen receives it. If either critic finds unsupported language, the coordinator permits exactly one correction—never an open-ended agent loop.”

**Screen:** In the completed brief, point to the Gemma model proof, one property-specific photo classification, an observable feature or missing-evidence warning, then `CONFIRMED`, `INFERRED`, and `UNKNOWN` claims.

**Say:**

> “This is not synthetic staging and Gemma does not create property content. It audits the real listing photos and preserves what they cannot prove. The brief separates confirmed, inferred, and unknown facts, then produces the questions I need before contacting an agent or placing a deposit.”

## 3:05–3:25 — Prove durable memory

**Action:** Close the brief, reload the browser, and click **Resume saved brief**.

**Say:**

> “This is persistent decision memory, not chat history. After a full reload, the approved profile revision, feedback, rankings, selected evidence, agent events, and completed brief remain available.”

## 3:25–3:48 — Prove architecture and Google Cloud

**Action:** Switch to the architecture diagram, then the live Google Cloud Console. Show both Cloud Run services and the matching Firestore profile or agent-run document. Keep credentials, project numbers, API keys, and billing details hidden.

**Say only after this deployment is real:**

> “The Next.js frontend and FastAPI backend run as separate Cloud Run services. Gemini 3.5 is orchestrated through Google ADK. Firestore stores durable decision and agent state, Cloud Storage holds validated images, and a scheduled Cloud Run job refreshes the catalog. Provider failure never creates fake listings; it falls back only to the last verified snapshot with its timestamp.”

## 3:48–3:58 — Close on the twist

**Action:** Return to the Decision Brief or the Why Your Ranking Changed panel.

**Say:**

> “Most housing apps learn what you click. Roamstead asks what matters, learns why you choose, and lets you control what it remembers. That is how you find a home abroad that actually fits your life.”

## Delivery notes

- Speak at roughly 125–135 words per minute. Pause on visible state changes instead of adding more explanation.
- Keep the cursor beside the evidence you are discussing; never wave it around the screen.
- Do not scroll through the entire catalog. One property detail and three compared homes are enough.
- Do not show source-site branding, ads, API keys, `.env` files, private URLs, or personally identifying data.
- If Gemini pauses, continue narrating the responsibility boundaries and let the live completion remain visible. Do not cut around it; the rubric rewards undeniable proof of action.
- Add English captions. Many judges will watch part of the video muted.
- The four non-negotiable visual beats are: **adaptive question → approval-gated profile proposal → visible ranking delta → three-specialist Decision Brief**.
