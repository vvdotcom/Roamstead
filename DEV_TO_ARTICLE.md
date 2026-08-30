---
title: "Building Roamstead: How Google Cloud Helped Me Create a Collaborative Housing Agent for Southeast Asia"
published: false
description: "How I turned messy cross-border property data into a persistent, approval-gated housing decision partner using Cloud Run, Firestore, Google ADK, Gemini, Gemma, and Google Maps."
tags: googlecloud, ai, hackathon, webdev
cover_image: ""
---

# Building Roamstead: How Google Cloud Helped Me Create a Collaborative Housing Agent for Southeast Asia

Moving to another country can unlock a better quality of life, lower housing costs, and a new sense of possibility. But finding a home across borders is much harder than opening a real estate website and choosing a listing.

Prices may be shown in an unfamiliar currency. Property descriptions may be written in another language. Addresses, neighborhood names, school access, and listing photographs can be inconsistent. Even when a property looks attractive, it can be difficult to separate verified facts from assumptions.

I saw an opportunity in that gap.

I built **Roamstead**, a collaborative housing decision partner for people exploring a move to Southeast Asia. It currently covers Ho Chi Minh City, Bangkok, and Kuala Lumpur, with Ho Chi Minh City as the most complete market experience.

You can try the deployed application here:

{% embed https://roamstead-web-113080100961.us-central1.run.app %}

Roamstead does not simply return properties from a search box. It learns what matters to a person, filters out homes that violate their hard requirements, explains why each remaining property fits, proposes preference changes when it notices a pattern, and waits for approval before changing anything.

The project started as a real estate discovery tool. Google Cloud helped me turn it into a persistent agentic system.

## The niche I wanted to serve

There is a growing group of Americans considering life abroad: remote workers, retirees, families, entrepreneurs, and people who simply want their housing budget to go further.

Southeast Asia is attractive because it can offer lower housing and living costs, strong food culture, international communities, modern private healthcare, and a different pace of life. But most U.S. property platforms are designed for domestic decisions. They assume the user already understands the location, currency, legal context, and listing conventions.

Roamstead starts from a different question:

> What would help someone make a confident housing decision in a market they do not yet understand?

That question changed the product. A list of attractive homes was not enough. The user needed translation, normalization, hard filtering, personal tradeoffs, evidence, memory, and clear next actions.

## My first non-negotiable decision: no synthetic listings

One of the earliest technical temptations was to generate a polished sample catalog. That would have made the frontend easier to build, but it would also have undermined the entire purpose of the product.

I decided that every displayed property had to come from a real listing source.

Roamstead now stores 240 real property records:

- 100 homes for sale and 100 rentals in Ho Chi Minh City
- 10 homes for sale and 10 rentals in Bangkok
- 10 homes for sale and 10 rentals in Kuala Lumpur

The source data is messy. Prices arrive in local currencies. Descriptions may need translation. Property types are inconsistent. Some photographs show a room; others show a document, floor plan, map, or marketing image.

The ingestion workflow normalizes the public presentation into English and U.S. dollars, validates the source page and image, and writes the accepted record to the database. Visitors search the saved catalog rather than triggering another model call on every page load.

That choice made the product more trustworthy and made the cloud architecture more important. Real data had to survive restarts, deployments, and model failures.

## The uncomfortable moments made the product better

This project did not move forward in a straight line.

At one point, the catalog pipeline was technically running, but the interface showed only one useful property in each category. At another point, a property had a photograph, but the photograph was really a document. The data passed a shallow check while failing the experience I was trying to create.

It would have been easy to fill the gaps with generated homes or placeholder images. Instead, I kept returning to the same rule: if the source could not support the property, Roamstead should not pretend that it could.

The same thing happened with the agent experience. An early clarification asked the user to choose between ocean access and proximity to a hospital in Ho Chi Minh City. The sentence sounded intelligent, but it was not responding to the actual profile or catalog. It felt like a script wearing an AI label.

I removed it.

That failure eventually led to the counterfactual ranking tool. Instead of asking Gemini to invent a plausible relocation question, the application now measures which preference changes would actually reorder the user’s qualified properties. Gemini can phrase the highest-value tradeoff, but it cannot invent the underlying options.

This became my working definition of useful agent behavior: not language that sounds smart, but behavior that is connected to real state and has a measurable consequence.

## Hard requirements belong to code, not a language model

Roamstead begins with a matching profile. The user chooses a city, whether they want to buy or rent, their budget, minimum bedrooms, minimum bathrooms, and whether they want an apartment, a house, or both.

Those are hard requirements.

If a home is over budget or has too few bedrooms, it is excluded. Gemini cannot argue with the filter, reinterpret it, or quietly place an attractive but ineligible property at the top.

The remaining properties receive a deterministic Fit Score based on editable lifestyle priorities such as:

- Healthcare access
- International-school proximity
- Food and daily-needs proximity
- Remote-work readiness
- Quiet surroundings
- Waterfront access

This separation became one of the most important architectural lessons in the project:

> Models should reason about ambiguity. Deterministic tools should enforce promises.

The same principle applies to prices, evidence states, profile revisions, and the number of correction attempts allowed during an agent run.

## From recommendation engine to collaborative partner

The biggest product improvement was moving beyond one-time recommendations.

Roamstead can ask one adaptive clarification based on the user’s actual profile and the current qualified catalog. A counterfactual ranking tool measures which possible preference changes would materially alter the top results. Gemini then turns that measured tradeoff into a concise question.

The question is dynamic, but its choices are bounded by real calculations.

When the user answers, Roamstead creates a proposed preference revision and shows its predicted impact. Nothing changes automatically. The user can accept, soften, or reject the proposal.

Only an accepted proposal creates a new profile revision and reranks the properties.

That approval boundary matters to me. A system that learns silently can become surprising or manipulative. A collaborative system should be able to say, “I noticed this pattern. Would you like me to update your profile?”

## Why Firestore became the memory of the product

Cloud Run is ideal for a hackathon application because it allowed me to deploy the Next.js frontend and FastAPI backend as separate containerized services without managing servers. Both services can scale to zero, and I capped each at one instance to keep the demo cost controlled.

But scale-to-zero also means an application cannot rely on one process staying alive forever.

Firestore became the durable memory behind Roamstead. It stores:

- Listings and their provenance
- User profiles and revision history
- Clarification answers
- Feedback and preference proposals
- Saved properties
- Agent runs and streamed events
- Decision Briefs
- Decision Watches and immutable evidence revisions
- Semantic decision memory

This was a turning point for the project. The agent stopped behaving like a temporary chat session. It could remember an approved decision, reconnect to an interrupted run, and restore a completed brief after the underlying Cloud Run instance was gone.

## Semantic memory without handing control to embeddings

People rarely express the same preference using the same words twice.

A user might say, “This street feels too loud,” and later reject another property because “I need somewhere calmer for work.” Exact-string matching would treat those as unrelated. Semantic memory can recognize that they express a similar concern.

Roamstead uses `gemini-embedding-001` to create 768-dimensional vectors for feedback, clarification answers, proposal decisions, and approved profile revisions. Firestore’s vector search retrieves a small, profile-isolated set of relevant memories.

I deliberately bounded that context:

- At most five memories
- A cosine-distance threshold
- A maximum 6,000-character context packet
- No raw vectors in the public API

The retrieved memories advise the agent, but they never change a hard filter or Fit Score. If vector generation fails, the deterministic product still works and the memory can be backfilled later.

This gave me the benefit of semantic continuity without making the ranking system opaque.

## Making the multi-agent workflow visible

For three shortlisted properties, Roamstead creates a Decision Brief through a Google ADK workflow.

The workflow combines deterministic function nodes with specialized model nodes:

1. Lock the profile, selected listings, and Fit Scores.
2. Retrieve a compact semantic-memory packet.
3. Use Gemini to analyze the three listings.
4. Run two Gemma critics in parallel.
5. Join both critic results.
6. Verify claims against deterministic evidence.
7. Allow exactly one correction if a critic challenges the analysis.
8. Compose and persist the final Decision Brief.

The first critic, `gemma-4-26b-a4b-it`, audits real property photographs. It identifies whether an image appears to be an interior, exterior, floor plan, document, or unknown image and flags claims the photographs cannot support.

The second critic, `gemma-4-31b-it`, checks the comparison against the user’s approved profile and retrieved decision memory. It looks for contradictions, superseded preferences, unsupported assumptions, and omitted tradeoffs.

Neither critic can change a price, Fit Score, profile, or evidence status.

Every workflow event is persisted before it is streamed to the browser. The interface shows function nodes, model nodes, parallel critics, the join, correction routing, and database persistence as they happen.

This made Google ADK more than an internal implementation detail. The orchestration itself became part of the product experience and part of the proof that the agents were doing distinct work.

## Google Cloud services that made Roamstead possible

Google Cloud gave each part of the system a natural home.

### Cloud Run

I deployed the Next.js web application and FastAPI/ADK backend as separate Cloud Run services. This let me use the right runtime for each layer while keeping deployment simple. Scale-to-zero and strict maximum-instance settings also made the project financially realistic for a public hackathon demo.

Cloud Run Jobs provide a bounded home for weekly catalog maintenance, approved Decision Watch checks, and agent evaluation. The weekly scheduler remains paused until a measured execution confirms the intended cost envelope.

### Firestore

Firestore is the production source of truth and the semantic-memory database. It gives the stateless Cloud Run services durable profiles, listings, agent traces, briefs, and vector search.

### Cloud Storage

Validated property photographs are stored separately from database records and served through Roamstead. This avoids hotlinking external image hosts and gives the application control over availability. Image redistribution rights still require careful review before a larger public launch.

### Secret Manager

Gemini credentials stay in Secret Manager and are read only by the identities that need them. The browser never receives the model API key. The Google Maps browser key is separate and restricted by API and website referrer.

### Google Maps Platform

The property workspace maps the complete filtered catalog, uses orange Fit Score pins, clusters dense areas, and supports normal and satellite views. Seeing the distribution of qualifying properties adds context that a ranked list cannot provide by itself.

### BigQuery and Cloud Trace

The agent workflow emits sanitized operational metadata for analytics and tracing. I can inspect model selection, tool stages, duration, workflow version, and failure modes without storing hidden reasoning, raw vectors, credentials, or private profile text.

### Pub/Sub, Cloud Build, and Artifact Registry

Pub/Sub carries maintenance completion and failure events. Cloud Build creates the container images, and Artifact Registry stores the deployable versions. Together, they made the system reproducible instead of dependent on my local machine.

## Going beyond retrieval with Decision Watch

A recommendation is useful, but a partner should be able to continue helping after the shortlist is created.

Roamstead’s Decision Watch examines the evidence gaps for exactly three selected properties and proposes the smallest useful due-diligence plan. Depending on the property, that plan can include:

- Rechecking source availability
- Comparing the advertised price
- Reviewing photographic evidence
- Renormalizing currency
- Verifying proximity claims

The user sees the plan before anything runs. After approval, the selected tools append immutable before-and-after evidence revisions. If a listing disappears or a claim becomes contradictory, its state becomes `UNKNOWN`. Roamstead never invents a replacement fact or synthetic property.

That feature brought the whole idea together: retrieve real information, reason about it, ask permission, take a bounded action, and persist the result.

## The hardest lessons I learned

### 1. A polished demo cannot compensate for weak data boundaries

The real-data-only rule created more work, but it also gave the product a reason to exist. Every design decision became clearer once I refused to fabricate listings or quietly replace missing evidence.

### 2. Persistence is part of agent intelligence

An agent that forgets everything after a container restart is not much of a partner. Firestore made memory, approval history, resumable workflows, and inspectable traces first-class product capabilities.

### 3. More models only help when they have different jobs

I did not want to add Gemma models only to increase a model count. The visual critic and memory critic solve different failure modes, and their outputs are visible in the final brief.

### 4. Streaming should reveal architecture, not imitate it

The interface does not reveal private chain-of-thought. It shows public action summaries, tool results, model identities, evidence states, and persisted checkpoints. This makes the system understandable without pretending internal reasoning is a product feature.

### 5. Cost constraints can improve architecture

Designing for a very small monthly demo budget pushed me toward scale-to-zero services, cached property snapshots, bounded context, one correction pass, paused schedules, and explicit concurrency limits. Those constraints made Roamstead more disciplined.

## What I would build next

Roamstead currently has three city markets, but the product architecture is designed for broader Southeast Asian coverage.

The next steps would be:

- Add more verified local data partners and city-specific evidence rules.
- Add user authentication and per-user ownership controls.
- Complete a formal review of listing-image redistribution rights.
- Add budget alerts, abuse protection, and production rate limits.
- Expand Decision Watch with local legal and professional service integrations.

I would rather add those carefully than expand the catalog with low-confidence or synthetic data.

## Closing thought

I started Roamstead thinking mostly about property search. I ended up thinking about trust, memory, approval, and the difference between an AI feature and an AI partner.

Google Cloud gave me the infrastructure to make that distinction real. Cloud Run made the application deployable. Firestore gave it durable memory and vector retrieval. Cloud Storage protected the property experience from fragile external image links. Secret Manager kept credentials out of the browser. Google Maps made an unfamiliar city spatially understandable. ADK, Gemini, and Gemma turned the final shortlist into a visible, reviewable decision workflow.

The result is not an agent that tries to decide where someone should live.

It is a partner that helps people make that decision with clearer evidence, personalized tradeoffs, and control over every consequential change.

---

**Live application:** [Roamstead on Google Cloud](https://roamstead-web-113080100961.us-central1.run.app)

**Demo video:** _Add the public video URL before publishing._

**Source repository:** _Add the public repository URL before publishing._
