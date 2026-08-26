from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from .agent import agent_enabled
from .gemma_critic import gemma_critic_enabled, gemma_model, gemma_provider
from .memory_critic import memory_critic_enabled, memory_critic_model
from .cloud import download_listing_image, persist_profile, persist_revision, publish_event
from .clarifications import answer_clarification, plan_clarification
from .data import CANDIDATES
from .decision_briefs import decision_brief_service
from .listing_fit import score_listing_results
from .listings.live_search import (
    LiveListingConfigurationError,
    LiveListingSearchError,
    live_listing_search,
)
from .listings.catalog import listing_catalog
from .listings.images import (
    available_gallery_size,
    cache_listing_image,
    cached_gallery_paths,
    cached_image_path,
    has_publishable_gallery,
    image_media_type,
    minimum_gallery_size,
    public_image_url,
)
from .models import (
    ActionPlan,
    AssistantReply,
    ClarificationAnswerRequest,
    ClarificationAnswerResponse,
    ClarificationPlanResponse,
    CreateSessionRequest,
    CreateDecisionBriefRequest,
    CreateDecisionBriefResponse,
    FeedbackRequest,
    HardConstraint,
    ListingSearchRequest,
    ListingSearchResult,
    PreferenceProposal,
    Preference,
    ProfileUpdateRequest,
    ProposalDecisionRequest,
    RuleEvidence,
    SemanticMemoryPublic,
    SessionMessage,
)
from .ranking import INITIAL_WEIGHTS, rank_candidates, ranking_deltas, weights_from_profile
from .store import store
from .semantic_memory import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    make_memory,
    persist_memory,
    public_memory,
    retrieve_memory,
    semantic_memory_enabled,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler: asyncio.Task | None = None
    if os.getenv("ENABLE_WEEKLY_LISTING_REFRESH", "1") != "0":
        scheduler = asyncio.create_task(
            listing_catalog.run_weekly_scheduler(),
            name="roamstead-weekly-listing-refresh",
        )
    try:
        yield
    finally:
        if scheduler:
            scheduler.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler


app = FastAPI(title="Roamstead API", version="0.1.0", lifespan=lifespan)
allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
if os.getenv("WEB_ORIGIN"):
    allowed_origins.append(os.environ["WEB_ORIGIN"].rstrip("/"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_session(session_id: str):
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def require_profile(profile_id: str):
    profile = store.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


def with_local_listing_images(item):
    gallery_size = available_gallery_size(item.id)
    image_urls = [public_image_url(item.id, index) for index in range(gallery_size)]
    if not image_urls:
        image_urls = [public_image_url(item.id)]
    return item.model_copy(update={"image_url": image_urls[0], "image_urls": image_urls})


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "roamstead-api",
        "deployment_mode": "CLOUD_RUN" if os.getenv("K_SERVICE") else "LOCAL",
        "agent": {
            "orchestration": "Google ADK",
            "model": os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash"),
            "provider": "VERTEX_AI" if os.getenv("GOOGLE_GENAI_USE_VERTEXAI") == "1" else "GEMINI_API",
            "execution_mode": "ADK_GEMINI" if agent_enabled() else "VERIFIED_CACHE",
            "gemma_critic": {
                "enabled": gemma_critic_enabled(),
                "model": gemma_model(),
                "provider": gemma_provider(),
            },
            "memory_critic": {
                "enabled": memory_critic_enabled(),
                "model": memory_critic_model(),
                "provider": "GEMINI_API",
            },
            "semantic_memory": {
                "enabled": semantic_memory_enabled(),
                "model": EMBEDDING_MODEL,
                "dimension": EMBEDDING_DIMENSION,
                "role": "advisory_context_only",
            },
        },
        "persistence": listing_catalog.status()["storage"],
        "integration_proof": "Successful persisted visual and memory audits plus a READY memory context are required; configuration alone is not proof.",
    }


@app.post("/api/v1/sessions")
def create_session(body: CreateSessionRequest | None = None):
    session = store.create_session((body or CreateSessionRequest()).housing_mode)
    return {
        "session": session,
        "profile": store.profiles[session.profile_id],
        "assistant": "Tell me what a good move needs to make possible for your life — not just what kind of home you want.",
    }


@app.post("/api/v1/sessions/{session_id}/message", response_model=AssistantReply)
def message(session_id: str, body: SessionMessage):
    session = require_session(session_id)
    profile = require_profile(session.profile_id)

    # Profile setup is intentionally direct. The earlier budget/ocean script
    # made assumptions about relocation costs and geography before the user
    # had reviewed their preferences.
    session.stage = "DISCOVERY"
    store.save_session(session)
    store.rankings[profile.profile_id] = rank_candidates(CANDIDATES, weights_from_profile(profile))
    return AssistantReply(
        message="Your Decision Profile is ready to review before matching real HCMC properties.",
        stage=session.stage,
        profile=profile,
        recommendations=store.rankings[profile.profile_id],
    )

@app.get("/api/v1/profiles/{profile_id}")
def get_profile(profile_id: str):
    return require_profile(profile_id)


@app.post("/api/v1/profiles/{profile_id}/clarification", response_model=ClarificationPlanResponse)
async def create_clarification(profile_id: str):
    profile = require_profile(profile_id)
    return await plan_clarification(profile)


@app.post(
    "/api/v1/profiles/{profile_id}/clarifications/{question_id}/answer",
    response_model=ClarificationAnswerResponse,
)
async def submit_clarification_answer(profile_id: str, question_id: str, body: ClarificationAnswerRequest):
    profile = require_profile(profile_id)
    try:
        result = answer_clarification(profile, question_id, body.option_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    persist_profile(profile.model_dump())
    selected = next((item for item in result.question.options if item.id == body.option_id), None)
    if selected:
        await persist_memory(
            listing_catalog.repository,
            make_memory(
                profile_id=profile_id,
                source_event_id=f"clarification-answer:{question_id}",
                kind="CLARIFICATION",
                preference_key=selected.preference_key,
                source_text=f"Clarification answer: {selected.label}. {selected.impact_summary}",
                transaction_mode="RENT" if any(item.key == "rent_budget" for item in profile.hard_constraints) else "BUY",
            ),
        )
    return result


@app.put("/api/v1/profiles/{profile_id}")
async def update_profile(profile_id: str, body: ProfileUpdateRequest):
    profile = require_profile(profile_id)
    allowed_priorities = {
        "budget",
        "space",
        "healthcare",
        "remote_work",
        "waterfront",
        "quiet",
        "international_school",
        "food_access",
    }
    unknown = set(body.priorities) - allowed_priorities
    if unknown or any(not 0 <= value <= 1 for value in body.priorities.values()):
        raise HTTPException(status_code=422, detail="Profile priorities must be recognized values from 0 to 1")

    property_types = list(dict.fromkeys(body.property_types))
    if not property_types:
        raise HTTPException(status_code=422, detail="Choose Apartment, House, or both")

    before_profile = deepcopy(profile.model_dump())
    before_ranking = deepcopy(store.rankings[profile_id])
    is_rent = any(item.key == "rent_budget" for item in profile.hard_constraints)

    constraints = {item.key: item for item in profile.hard_constraints}

    def set_constraint(key: str, label: str, operator: str, value: str | int) -> None:
        if key in constraints:
            constraints[key].label = label
            constraints[key].operator = operator
            constraints[key].value = value
        else:
            item = HardConstraint(key=key, label=label, operator=operator, value=value)
            profile.hard_constraints.append(item)
            constraints[key] = item

    budget_key = "rent_budget" if is_rent else "budget"
    set_constraint(
        budget_key,
        f"${body.budget_usd:,} monthly rent" if is_rent else f"${body.budget_usd:,} purchase budget",
        "<=",
        body.budget_usd,
    )
    set_constraint("min_beds", f"At least {body.min_beds} bedroom{'s' if body.min_beds != 1 else ''}", ">=", body.min_beds)
    set_constraint("min_baths", f"At least {body.min_baths} bathroom{'s' if body.min_baths != 1 else ''}", ">=", body.min_baths)
    set_constraint("max_international_school_minutes", f"International school within {body.max_international_school_minutes} min", "<=", body.max_international_school_minutes)
    set_constraint("max_food_minutes", f"Food and daily needs within {body.max_food_minutes} min", "<=", body.max_food_minutes)
    set_constraint("property_types", ", ".join(property_types), "in", ",".join(property_types))

    labels = {
        "budget": "Stay within budget",
        "space": "Bedrooms and bathrooms",
        "healthcare": "Healthcare access",
        "remote_work": "Reliable remote work",
        "waterfront": "Waterfront access",
        "quiet": "Quiet neighborhood",
        "international_school": "International-school access",
        "food_access": "Food and daily-needs proximity",
    }
    preferences = {item.key: item for item in profile.preferences}
    for key in allowed_priorities:
        value = body.priorities.get(key, preferences.get(key).weight if preferences.get(key) else 0.5)
        if key in preferences:
            preferences[key].weight = value
            preferences[key].label = labels[key]
            preferences[key].status = "confirmed"
        else:
            profile.preferences.append(Preference(key=key, label=labels[key], weight=value))

    profile.version += 1
    after_ranking = rank_candidates(CANDIDATES, weights_from_profile(profile))
    store.rankings[profile_id] = after_ranking
    revision = {
        "before": before_profile,
        "after": profile.model_dump(),
        "decision": "PROFILE_EDIT",
    }
    store.save_revision(profile_id, revision)
    store.save_profile(profile)
    persist_revision(profile_id, revision)
    persist_profile(profile.model_dump())
    deltas = ranking_deltas(before_ranking, after_ranking)
    publish_event("ranking.recomputed", {"profile_id": profile_id, "deltas": [item.model_dump() for item in deltas]})
    await persist_memory(
        listing_catalog.repository,
        make_memory(
            profile_id=profile_id,
            source_event_id=f"profile-revision:{profile_id}:v{profile.version}",
            kind="PROFILE_REVISION",
            source_text=(
                f"Approved profile revision {profile.version}. Budget ${body.budget_usd}; minimum {body.min_beds} bedrooms and "
                f"{body.min_baths} bathrooms; property types {', '.join(property_types)}; priorities "
                + ", ".join(f"{key} {value:.2f}" for key, value in sorted(body.priorities.items()))
            ),
            transaction_mode="RENT" if is_rent else "BUY",
        ),
    )
    return {"profile": profile, "recommendations": after_ranking, "deltas": deltas}


@app.get("/api/v1/recommendations/neighborhoods")
def neighborhoods(profile_id: str = Query(...)):
    require_profile(profile_id)
    return {"items": store.rankings[profile_id]}


@app.post("/api/v1/profiles/{profile_id}/feedback")
async def feedback(profile_id: str, body: FeedbackRequest):
    profile = require_profile(profile_id)
    candidate = next((item for item in CANDIDATES if item.id == body.target_id), None)
    listing_item = listing_catalog.get(body.target_id)
    if not candidate and not listing_item:
        raise HTTPException(status_code=404, detail="Property not found")
    event = store.record_feedback(
        profile_id,
        body.target_id,
        body.action,
        body.reason,
        target_name=candidate.name if candidate else listing_item.title,
        target_type="NEIGHBORHOOD" if candidate else "LISTING",
    )
    store.save_profile(profile)
    persist_profile(profile.model_dump())
    publish_event("feedback.recorded", event.model_dump())

    proposal = None
    proposal_config = {
        "TOO_URBAN": ("quiet", "Quieter surroundings", 0.85, "You repeatedly passed on properties because the surroundings felt too urban."),
        "TOO_EXPENSIVE": ("budget", "Stricter budget fit", 1.0, "You repeatedly passed on properties because their advertised price felt too high."),
        "TOO_SMALL": ("space", "More bedrooms and bathrooms", 0.95, "You repeatedly passed on properties because they felt too small."),
        "SCHOOL_TOO_FAR": ("international_school", "Closer international-school access", 0.95, "You repeatedly passed on properties because international-school access felt too far."),
        "FOOD_TOO_FAR": ("food_access", "Closer food and daily needs", 0.90, "You repeatedly passed on properties because food and daily needs felt too far away."),
    }
    memory_context = None
    signal_count = 1
    rejected_memory = False
    if body.reason in proposal_config:
        proposal_key, proposal_label, _, _ = proposal_config[body.reason]
        note = (body.note or "").strip()
        source_text = (
            f"Rejected {event.target_name}. Preference category: {proposal_label}. "
            + (f"User note: {note}" if note else f"Structured reason: {body.reason.replace('_', ' ').lower()}.")
        )
        memory = await persist_memory(
            listing_catalog.repository,
            make_memory(
                profile_id=profile_id,
                source_event_id=event.id,
                kind="FEEDBACK",
                preference_key=proposal_key,
                source_text=source_text,
                target_id=event.target_id,
                target_name=event.target_name,
                transaction_mode=listing_item.transaction_mode if listing_item else None,
            ),
        )
        memory_context = await retrieve_memory(
            listing_catalog.repository,
            profile_id,
            source_text,
            preference_key=proposal_key,
            exclude_ids={memory.id},
        )
        if memory_context.status == "READY":
            active_matches = [item for item in memory_context.matches if item.decision_status == "ACTIVE"]
            signal_count += len(active_matches)
            rejected_memory = any(item.decision_status == "REJECTED" for item in memory_context.matches)
        else:
            signal_count = len(
                [item for item in profile.feedback if item.action == "REJECT" and item.reason == body.reason]
            )

    if signal_count >= 2 and body.reason in proposal_config and not rejected_memory:
        proposal_key, proposal_label, proposed_floor, rationale = proposal_config[body.reason]
        existing = next(
            (
                item
                for proposal_id, item in store.proposals.items()
                if store.proposal_profiles.get(proposal_id) == profile_id
                and item.key == proposal_key
                and item.status == "AWAITING_CONFIRMATION"
            ),
            None,
        )
        old_weight = next((item.weight for item in profile.preferences if item.key == proposal_key), INITIAL_WEIGHTS.get(proposal_key, 0.5))
        proposal = existing or PreferenceProposal(
            id=f"proposal-{uuid4().hex[:8]}",
            key=proposal_key,
            label=proposal_label,
            rationale=rationale,
            evidence_count=signal_count,
            old_weight=old_weight,
            proposed_weight=max(old_weight, proposed_floor),
        )
        store.save_proposal(profile_id, proposal)
    return {"event": event, "profile": profile, "proposal": proposal, "memory_context": memory_context}


@app.get("/api/v1/profiles/{profile_id}/semantic-memory", response_model=list[SemanticMemoryPublic])
def semantic_memory(profile_id: str):
    require_profile(profile_id)
    return [public_memory(item) for item in listing_catalog.repository.list_semantic_memory(profile_id)]


@app.post("/api/v1/profiles/{profile_id}/preference-proposals/{proposal_id}/decision")
async def decide_proposal(profile_id: str, proposal_id: str, body: ProposalDecisionRequest):
    profile = require_profile(profile_id)
    proposal = store.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if store.proposal_profiles.get(proposal_id) != profile_id:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "AWAITING_CONFIRMATION":
        raise HTTPException(status_code=409, detail="Proposal already decided")

    before_profile = deepcopy(profile.model_dump())
    before_ranking = deepcopy(store.rankings[profile_id])
    if body.decision == "ACCEPT":
        proposal.status = "ACCEPTED"
        preference = next(item for item in profile.preferences if item.key == proposal.key)
        preference.weight = proposal.proposed_weight
        preference.label = proposal.label
    elif body.decision == "SOFTEN":
        proposal.status = "SOFTENED"
        preference = next(item for item in profile.preferences if item.key == proposal.key)
        preference.weight = round((proposal.old_weight + proposal.proposed_weight) / 2, 2)
    else:
        proposal.status = "REJECTED"

    profile.version += 1
    revision = {
        "before": before_profile,
        "after": profile.model_dump(),
        "decision": body.decision,
        "proposal_id": proposal_id,
    }
    store.save_revision(profile_id, revision)
    store.save_proposal(profile_id, proposal)
    persist_revision(profile_id, revision)
    after_ranking = rank_candidates(CANDIDATES, weights_from_profile(profile))
    store.rankings[profile_id] = after_ranking
    deltas = ranking_deltas(before_ranking, after_ranking)
    store.save_profile(profile)
    persist_profile(profile.model_dump())
    publish_event("ranking.recomputed", {"profile_id": profile_id, "deltas": [item.model_dump() for item in deltas]})
    await persist_memory(
        listing_catalog.repository,
        make_memory(
            profile_id=profile_id,
            source_event_id=f"proposal-decision:{proposal_id}",
            kind="PROPOSAL_DECISION",
            preference_key=proposal.key,
            source_text=(
                f"{body.decision.title()} proposal '{proposal.label}' from weight {proposal.old_weight:.2f} "
                f"toward {proposal.proposed_weight:.2f}. {proposal.rationale}"
            ),
            transaction_mode="RENT" if any(item.key == "rent_budget" for item in profile.hard_constraints) else "BUY",
            decision_status="REJECTED" if body.decision == "REJECT" else "ACTIVE",
        ),
    )
    return {
        "proposal": proposal,
        "profile": profile,
        "recommendations": after_ranking,
        "deltas": deltas,
        "explanation": (
            f"The ranking was recalculated because you approved {proposal.label.lower()} as a stronger priority. "
            "Every hard constraint stayed unchanged."
            if body.decision != "REJECT"
            else "I kept your original profile. No ranking weights changed."
        ),
    }


@app.post("/api/v1/profiles/{profile_id}/undo")
def undo(profile_id: str):
    profile = require_profile(profile_id)
    if not store.revisions[profile_id]:
        raise HTTPException(status_code=409, detail="Nothing to undo")
    revision = store.revisions[profile_id].pop()
    restored = profile.__class__.model_validate(revision["before"])
    if store.profile_repository:
        store.profile_repository.save_revision(
            profile_id,
            {
                "before": profile.model_dump(),
                "after": restored.model_dump(),
                "decision": "UNDO",
                "undid_decision": revision.get("decision"),
            },
        )
    store.save_profile(restored)
    store.rankings[profile_id] = rank_candidates(CANDIDATES, weights_from_profile(restored))
    persist_profile(restored.model_dump())
    return {"profile": restored, "recommendations": store.rankings[profile_id]}


@app.get("/api/v1/listings/status")
def listing_search_status():
    return {
        "provider": "Gemini + Google Search",
        "source_domain": "batdongsan.com.vn",
        "configured": live_listing_search.configured,
        "synthetic_fallback": False,
        "catalog": listing_catalog.status(),
    }


@app.post("/api/v1/listings/search", response_model=ListingSearchResult)
async def search_listings(body: ListingSearchRequest):
    profile = require_profile(body.profile_id)
    try:
        # Browser refreshes read the durable catalog. Only the weekly coordinator
        # is allowed to spend a new Gemini grounded-search request.
        items = await listing_catalog.listings(body.transaction_mode, body.limit)
    except LiveListingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LiveListingSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    catalog_state = listing_catalog.repository.status(body.transaction_mode)
    pending_gallery_verification = sum(not has_publishable_gallery(item.id) for item in items)
    items = [item for item in items if has_publishable_gallery(item.id)]
    items = score_listing_results(
        items,
        profile,
        store.rankings[profile.profile_id],
        body.focused_neighborhood_id,
    )
    items = [with_local_listing_images(item) for item in items]
    return ListingSearchResult(
        items=items,
        requested=body.limit,
        returned=len(items),
        transaction_mode=body.transaction_mode,
        partial=len(items) < body.limit,
        minimum_photos_per_listing=minimum_gallery_size(),
        pending_gallery_verification=pending_gallery_verification,
        searched_at=(
            catalog_state["last_success_at"]
            or catalog_state["last_attempt_at"]
            or items[0].source_checked_at
        ),
        last_refreshed_at=catalog_state["last_success_at"],
        next_refresh_at=catalog_state["next_refresh_at"],
        storage=listing_catalog.status()["storage"],
    )


@app.get("/api/v1/listing-images/{listing_id}")
async def listing_image(listing_id: str):
    item = listing_catalog.get(listing_id)
    if not item:
        raise HTTPException(status_code=404, detail="Listing image not found")
    path = cached_image_path(listing_id) or await cache_listing_image(item)
    if not path:
        cloud_image = await asyncio.to_thread(download_listing_image, listing_id, 0)
        if cloud_image:
            content, media_type = cloud_image
            return Response(content, media_type=media_type, headers={"Cache-Control": "public, max-age=86400, immutable"})
        raise HTTPException(status_code=404, detail="Validated property image is unavailable")
    return FileResponse(
        path,
        media_type=image_media_type(path),
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@app.get("/api/v1/listing-images/{listing_id}/{image_index}")
async def listing_gallery_image(listing_id: str, image_index: int):
    if image_index < 1:
        raise HTTPException(status_code=404, detail="Listing image not found")
    item = listing_catalog.get(listing_id)
    if not item:
        raise HTTPException(status_code=404, detail="Listing image not found")
    path = cached_image_path(listing_id, image_index)
    if not path:
        cloud_image = await asyncio.to_thread(download_listing_image, listing_id, image_index)
        if cloud_image:
            content, media_type = cloud_image
            return Response(content, media_type=media_type, headers={"Cache-Control": "public, max-age=86400, immutable"})
        raise HTTPException(status_code=404, detail="Validated property image is unavailable")
    return FileResponse(
        path,
        media_type=image_media_type(path),
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@app.get("/api/v1/listings/{listing_id}")
def listing(listing_id: str):
    item = listing_catalog.get(listing_id)
    if not item:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not has_publishable_gallery(item.id):
        raise HTTPException(
            status_code=404,
            detail=f"Listing is pending verification of at least {minimum_gallery_size()} exact property photos",
        )
    return with_local_listing_images(item)


@app.get("/api/v1/rule-evidence", response_model=RuleEvidence)
def rule_evidence():
    return RuleEvidence(
        country="Vietnam",
        topic="Foreign ownership of commercial housing",
        summary=(
            "Current official legislation includes routes for eligible foreign individuals to own certain homes in qualifying commercial housing projects, "
            "subject to entry, project, location, quantity and term conditions. A listing alone does not prove eligibility for a specific buyer or unit."
        ),
        source_title="Law on Housing No. 27/2023/QH15",
        source_url="https://vanban.chinhphu.vn/default.aspx?docid=209627&pageid=27160",
        publisher="Vietnam Government legal document portal",
        last_checked="2026-08-18",
    )


@app.post("/api/v1/saved")
def save(profile_id: str = Query(...), item_id: str = Query(...)):
    require_profile(profile_id)
    if not listing_catalog.get(item_id):
        raise HTTPException(status_code=404, detail="Property not found")
    return {"saved": sorted(store.save_listing(profile_id, item_id))}


@app.get("/api/v1/saved")
def saved(profile_id: str = Query(...)):
    require_profile(profile_id)
    return {"saved": sorted(store.saved.setdefault(profile_id, store.profile_repository.list_saved_items(profile_id)))}


@app.post("/api/v1/decision-briefs", response_model=CreateDecisionBriefResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_decision_brief(body: CreateDecisionBriefRequest):
    profile = require_profile(body.profile_id)
    try:
        result = await decision_brief_service.create(body, profile)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    publish_event("decision_brief.queued", {"profile_id": body.profile_id, "run_id": result.run.id})
    return result


@app.get("/api/v1/decision-briefs/{run_id}")
def get_decision_brief(run_id: str):
    brief = decision_brief_service.repository.get_decision_brief(run_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Decision Brief not found")
    return brief


@app.get("/api/v1/profiles/{profile_id}/decision-briefs")
def list_decision_briefs(profile_id: str):
    require_profile(profile_id)
    return {"items": decision_brief_service.repository.list_decision_briefs(profile_id)}


@app.get("/api/v1/decision-briefs/{run_id}/events")
async def decision_brief_events(run_id: str, request: Request, after: int = Query(default=0, ge=0)):
    run = decision_brief_service.repository.get_agent_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    async def stream():
        # Flush headers before execution starts so every subsequent database
        # write can be observed by the connected browser in real time.
        yield "retry: 1500\n: connected " + (" " * 2048) + "\n\n"
        await decision_brief_service.ensure_execution(run_id)
        header_sequence = request.headers.get("last-event-id", "0")
        try:
            last_sequence = max(after, int(header_sequence))
        except ValueError:
            last_sequence = after
        heartbeat = 0
        while True:
            events = decision_brief_service.repository.list_agent_events(run_id)
            for event in events:
                if event.sequence <= last_sequence:
                    continue
                last_sequence = event.sequence
                yield f"id: {event.sequence}\nevent: {event.event_type.lower()}\ndata: {json.dumps(event.model_dump(mode='json'))}\n\n"

            current = decision_brief_service.repository.get_agent_run(run_id)
            if current and current.status in {"COMPLETED", "FAILED"}:
                yield f"event: stream_end\ndata: {json.dumps({'run_id': run_id, 'status': current.status, 'error': current.error})}\n\n"
                break

            heartbeat += 1
            if heartbeat % 50 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/plans", response_model=ActionPlan)
def build_plan(profile_id: str = Query(...)):
    profile = require_profile(profile_id)
    is_rent = any(item.key == "rent_budget" for item in profile.hard_constraints)
    saved_ids = store.saved[profile_id]
    names = [item.title for item in listing_catalog.cached_items() if item.id in saved_ids]
    if not names:
        names = [store.rankings[profile_id][0].name]
    return ActionPlan(
        id=f"plan-{uuid4().hex[:8]}",
        title="Your Ho Chi Minh City decision sprint",
        shortlist=names,
        steps=[
            {
                "phase": "Before the visit",
                "task": (
                    "Request the draft lease, included fees, deposit terms and proof that the landlord or agent is authorized to lease the home."
                    if is_rent
                    else "Confirm the specific project's foreign-ownership eligibility and quota with an independent qualified local professional."
                ),
            },
            {"phase": "Day 1", "task": "Test the Nha Be-to-hospital route during weekday traffic and verify the quoted travel time."},
            {"phase": "Day 2", "task": "Work a full remote day from the shortlisted building and test backup internet options."},
            {
                "phase": "Decision gate",
                "task": (
                    "Compare rent, building fees, utilities and deposit cash against the protected $1,500 monthly ceiling."
                    if is_rent
                    else "Compare total closing, furnishing and relocation costs against the protected $175,000 purchase ceiling."
                ),
            },
        ],
        unresolved_questions=[
            "Which household members need visa or residence planning?",
            "Is an international school needed now or later?",
            "What lease length and early-termination terms fit the relocation plan?" if is_rent else "Would renting for 3–6 months reduce purchase risk?",
        ],
    )
