from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HardConstraint(BaseModel):
    key: str
    label: str
    operator: str
    value: str | int | float | bool
    locked: bool = True


class Preference(BaseModel):
    key: str
    label: str
    weight: float = Field(ge=0, le=1)
    status: Literal["confirmed", "emerging"] = "confirmed"


class FeedbackEvent(BaseModel):
    id: str
    target_id: str
    target_name: str
    target_type: Literal["LISTING", "NEIGHBORHOOD"] = "LISTING"
    action: Literal["REJECT", "SAVE"]
    reason: str
    timestamp: str = Field(default_factory=now_iso)


class ClarificationOption(BaseModel):
    id: str
    label: str
    preference_key: str | None = None
    proposed_weight: float | None = Field(default=None, ge=0, le=1)
    predicted_top_changes: int = Field(default=0, ge=0)
    impact_summary: str


class ClarificationTurn(BaseModel):
    id: str
    profile_id: str
    profile_version: int
    question: str
    why_asked: str
    eligible_listing_count: int = Field(ge=0)
    options: list[ClarificationOption] = Field(min_length=2, max_length=3)
    status: Literal["AWAITING_ANSWER", "PROPOSAL_CREATED", "NO_CHANGE"] = "AWAITING_ANSWER"
    selected_option_id: str | None = None
    run_id: str
    created_at: str = Field(default_factory=now_iso)
    answered_at: str | None = None


class DecisionProfile(BaseModel):
    profile_id: str
    version: int = 1
    hard_constraints: list[HardConstraint]
    preferences: list[Preference]
    feedback: list[FeedbackEvent] = Field(default_factory=list)
    clarifications: list[ClarificationTurn] = Field(default_factory=list)


class ScoreComponents(BaseModel):
    budget: int
    healthcare: int
    remote_work: int
    waterfront: int
    quiet: int
    international_school: int
    food_access: int


class Candidate(BaseModel):
    id: str
    name: str
    district: str
    tagline: str
    image: str
    score: int = 0
    rank: int = 0
    components: ScoreComponents
    price_from_usd: int
    rent_from_usd: int
    hospital_minutes: int
    waterfront_minutes: int
    international_school_minutes: int
    food_minutes: int
    homes: int
    map_x: int
    map_y: int
    tradeoff: str
    rejected: bool = False


class RankingDelta(BaseModel):
    candidate_id: str
    name: str
    previous_rank: int
    new_rank: int
    previous_score: int
    new_score: int


class PreferenceProposal(BaseModel):
    id: str
    key: str = "quiet"
    label: str = "Quieter, lower-density neighborhoods"
    rationale: str = "Repeated feedback suggests this preference may matter more than the current profile shows."
    evidence_count: int
    old_weight: float
    proposed_weight: float
    source_clarification_id: str | None = None
    predicted_impact: str | None = None
    status: Literal["AWAITING_CONFIRMATION", "ACCEPTED", "SOFTENED", "REJECTED"] = "AWAITING_CONFIRMATION"


class Session(BaseModel):
    id: str
    profile_id: str
    housing_mode: Literal["BUY", "RENT"] = "BUY"
    stage: Literal["NEW", "BUDGET", "WATERFRONT", "DISCOVERY"] = "NEW"
    created_at: str = Field(default_factory=now_iso)


class SessionMessage(BaseModel):
    message: str = ""
    answer_key: str | None = None
    answer_value: str | bool | int | None = None


class CreateSessionRequest(BaseModel):
    housing_mode: Literal["BUY", "RENT"] = "BUY"


class AssistantReply(BaseModel):
    message: str
    stage: str
    question: dict | None = None
    profile: DecisionProfile | None = None
    recommendations: list[Candidate] | None = None


class FeedbackRequest(BaseModel):
    target_id: str
    action: Literal["REJECT", "SAVE"]
    reason: str
    note: str | None = Field(default=None, max_length=1000)


class ProposalDecisionRequest(BaseModel):
    decision: Literal["ACCEPT", "SOFTEN", "REJECT"]


class ClarificationAnswerRequest(BaseModel):
    option_id: str = Field(min_length=1, max_length=80)


class ClarificationPlanResponse(BaseModel):
    run: "AgentRun"
    question: ClarificationTurn | None = None
    events: list["AgentEvent"] = Field(default_factory=list)
    reused: bool = False


class ClarificationAnswerResponse(BaseModel):
    profile: DecisionProfile
    question: ClarificationTurn
    proposal: PreferenceProposal | None = None
    events: list["AgentEvent"] = Field(default_factory=list)


class ProfileUpdateRequest(BaseModel):
    budget_usd: int = Field(ge=100, le=20_000_000)
    min_beds: int = Field(default=1, ge=0, le=20)
    min_baths: int = Field(default=1, ge=0, le=20)
    max_international_school_minutes: int = Field(default=30, ge=5, le=120)
    max_food_minutes: int = Field(default=15, ge=5, le=60)
    property_types: list[Literal["Apartment", "House"]] = Field(default_factory=list, max_length=2)
    priorities: dict[str, float]


class Listing(BaseModel):
    id: str
    neighborhood_id: str
    title: str
    transaction_mode: Literal["BUY", "RENT"]
    price_vnd: int = Field(gt=0)
    price_usd: int = Field(gt=0)
    price_band: Literal["LOW", "MEDIUM", "HIGH", "ULTRA_HIGH"]
    district: str
    address: str | None = None
    beds: int | None = Field(default=None, ge=0)
    baths: int | None = Field(default=None, ge=0)
    area_sqm: float | None = Field(default=None, gt=0)
    image_url: str = Field(min_length=8)
    image_urls: list[str] = Field(default_factory=list)
    fit_score: int = Field(default=0, ge=0, le=100)
    fit_breakdown: dict[str, int] = Field(default_factory=dict)
    fit_reasons: list[str] = Field(default_factory=list)
    hospital_minutes: int | None = Field(default=None, ge=0)
    waterfront_minutes: int | None = Field(default=None, ge=0)
    international_school_minutes_estimate: int | None = Field(default=None, ge=0)
    food_minutes_estimate: int | None = Field(default=None, ge=0)
    property_type: str
    source_url: str
    source_domain: str = "batdongsan.com.vn"
    source_title: str | None = None
    source_checked_at: str = Field(default_factory=now_iso)
    demo: Literal[False] = False


class ListingSearchRequest(BaseModel):
    transaction_mode: Literal["BUY", "RENT"]
    profile_id: str = Field(min_length=1)
    focused_neighborhood_id: str | None = None
    limit: int = Field(default=100, ge=1, le=100)
    refresh: bool = False


class ListingSearchResult(BaseModel):
    items: list[Listing]
    requested: int
    returned: int
    transaction_mode: Literal["BUY", "RENT"]
    live: Literal[True] = True
    partial: bool
    minimum_photos_per_listing: int = 1
    pending_gallery_verification: int = 0
    searched_at: str = Field(default_factory=now_iso)
    provider: str = "Gemini + Google Search"
    source_domain: str = "batdongsan.com.vn"
    catalog_cached: Literal[True] = True
    last_refreshed_at: str | None = None
    next_refresh_at: str | None = None
    storage: str = "SQLite"


class RuleEvidence(BaseModel):
    country: str
    topic: str
    status: Literal["REQUIRES_VERIFICATION"] = "REQUIRES_VERIFICATION"
    summary: str
    source_title: str
    source_url: str
    publisher: str
    last_checked: str
    confidence: Literal["MEDIUM"] = "MEDIUM"


class ActionPlan(BaseModel):
    id: str
    title: str
    shortlist: list[str]
    steps: list[dict[str, str]]
    unresolved_questions: list[str]


EvidenceStatus = Literal["CONFIRMED", "INFERRED", "UNKNOWN"]


class AgentEvent(BaseModel):
    id: str
    run_id: str
    sequence: int = Field(ge=1)
    event_type: Literal[
        "CLARIFICATION",
        "AGENT_STATUS",
        "TOOL_RESULT",
        "PROFILE_PROPOSAL",
        "RECOMMENDATION",
        "RECOVERABLE_ERROR",
        "SPECIALIST_STARTED",
        "SPECIALIST_COMPLETED",
        "CORRECTION_REQUESTED",
        "SEMANTIC_MEMORY_STARTED",
        "SEMANTIC_MEMORY_COMPLETED",
        "RUN_DEGRADED",
        "RUN_COMPLETED",
    ]
    actor: str
    title: str
    summary: str
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"] = "COMPLETED"
    phase: str | None = None
    model: str | None = None
    provider: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    public_payload: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class AgentRun(BaseModel):
    id: str
    profile_id: str
    run_type: Literal["SESSION", "CLARIFICATION", "DECISION_BRIEF"]
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"] = "QUEUED"
    model: str = "gemini-3.5-flash"
    orchestration: str = "Google ADK"
    execution_mode: Literal["ADK_GEMINI", "VERIFIED_CACHE"] = "VERIFIED_CACHE"
    idempotency_key: str
    input_payload: dict = Field(default_factory=dict)
    current_stage: str = "QUEUED"
    completed_stages: list[str] = Field(default_factory=list)
    phase_outputs: dict = Field(default_factory=dict)
    models_used: list[str] = Field(default_factory=list)
    degraded: bool = False
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    error: str | None = None


class EvidenceClaim(BaseModel):
    id: str
    listing_id: str
    label: str
    value: str
    status: EvidenceStatus
    source_url: str
    observed_at: str
    explanation: str


class VisualImageAssessment(BaseModel):
    image_index: int = Field(ge=0)
    image_url: str
    classification: Literal["INTERIOR", "EXTERIOR", "FLOOR_PLAN", "DOCUMENT", "UNKNOWN"]
    observations: list[str] = Field(default_factory=list, max_length=4)
    warnings: list[str] = Field(default_factory=list, max_length=4)
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"


class PropertyVisualAudit(BaseModel):
    listing_id: str
    verdict: Literal["SUPPORTED", "CHALLENGE", "INSUFFICIENT"]
    images: list[VisualImageAssessment] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list, max_length=5)
    missing_evidence: list[str] = Field(default_factory=list, max_length=5)
    suggested_questions: list[str] = Field(default_factory=list, max_length=5)


class VisualEvidenceAudit(BaseModel):
    verdict: Literal["SUPPORTED", "CHALLENGE"]
    summary: str
    properties: list[PropertyVisualAudit] = Field(default_factory=list)
    challenged_claims: list[str] = Field(default_factory=list, max_length=8)
    model: str
    provider: Literal["GEMINI_API", "CLOUD_RUN_VLLM"]
    analyzed_photo_count: int = Field(ge=0)
    succeeded: bool = True
    created_at: str = Field(default_factory=now_iso)


class SemanticMemoryItem(BaseModel):
    id: str
    profile_id: str
    source_event_id: str
    kind: Literal["FEEDBACK", "CLARIFICATION", "PROPOSAL_DECISION", "PROFILE_REVISION"]
    preference_key: str | None = None
    source_text: str = Field(min_length=1, max_length=6000)
    target_id: str | None = None
    target_name: str | None = None
    city: str | None = None
    transaction_mode: Literal["BUY", "RENT"] | None = None
    decision_status: Literal["ACTIVE", "REJECTED", "SUPERSEDED"] = "ACTIVE"
    embedding_status: Literal["READY", "PENDING_EMBEDDING"] = "PENDING_EMBEDDING"
    embedding: list[float] = Field(default_factory=list, max_length=2048, repr=False)
    embedding_model: str = "gemini-embedding-001"
    embedding_dimension: int = Field(default=768, ge=1, le=2048)
    schema_version: int = 1
    error_code: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class SemanticMemoryPublic(BaseModel):
    id: str
    source_event_id: str
    kind: str
    preference_key: str | None = None
    source_text: str
    target_id: str | None = None
    target_name: str | None = None
    city: str | None = None
    transaction_mode: str | None = None
    decision_status: str
    embedding_status: str
    embedding_model: str
    created_at: str


class MemoryContextMatch(BaseModel):
    memory_id: str
    kind: str
    preference_key: str | None = None
    text: str
    target_name: str | None = None
    city: str | None = None
    decision_status: str = "ACTIVE"
    cosine_distance: float = Field(ge=0, le=2)
    created_at: str


class MemoryContextPacket(BaseModel):
    query: str
    matches: list[MemoryContextMatch] = Field(default_factory=list, max_length=5)
    considered_count: int = Field(default=0, ge=0)
    selected_count: int = Field(default=0, ge=0, le=5)
    excluded_count: int = Field(default=0, ge=0)
    context_characters: int = Field(default=0, ge=0, le=6000)
    model: str = "gemini-embedding-001"
    dimension: int = Field(default=768, ge=1, le=2048)
    status: Literal["READY", "UNAVAILABLE"] = "UNAVAILABLE"
    error_code: str | None = None


class MemoryConsistencyAudit(BaseModel):
    verdict: Literal["CONSISTENT", "CHALLENGE", "INSUFFICIENT"]
    summary: str = Field(min_length=1, max_length=500)
    relevant_memory_ids: list[str] = Field(default_factory=list, max_length=8)
    conflicting_preferences: list[str] = Field(default_factory=list, max_length=6)
    superseded_preferences: list[str] = Field(default_factory=list, max_length=6)
    unsupported_user_assumptions: list[str] = Field(default_factory=list, max_length=6)
    omitted_tradeoffs: list[str] = Field(default_factory=list, max_length=6)
    suggested_questions: list[str] = Field(default_factory=list, max_length=5)
    model: str = "gemma-4-31b-it"
    provider: Literal["GEMINI_API"] = "GEMINI_API"
    duration_ms: int = Field(default=0, ge=0)
    succeeded: bool = True
    created_at: str = Field(default_factory=now_iso)


class DecisionBriefProperty(BaseModel):
    listing_id: str
    title: str
    district: str
    price_usd: int
    transaction_mode: Literal["BUY", "RENT"]
    fit_score: int
    fit_reasons: list[str]
    image_urls: list[str]
    source_url: str
    source_checked_at: str
    evidence: list[EvidenceClaim]
    tradeoffs: list[str]
    verification_questions: list[str]
    visual_audit: PropertyVisualAudit | None = None


class DecisionBrief(BaseModel):
    run_id: str
    profile_id: str
    profile_version: int
    status: Literal["RUNNING", "COMPLETED", "FAILED"] = "RUNNING"
    title: str = "Ho Chi Minh City Decision Brief"
    executive_summary: str = ""
    properties: list[DecisionBriefProperty] = Field(default_factory=list)
    recommendation: str = ""
    next_actions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    visual_audit: VisualEvidenceAudit | None = None
    memory_context: MemoryContextPacket | None = None
    memory_audit: MemoryConsistencyAudit | None = None
    models_used: list[str] = Field(default_factory=list)
    degraded: bool = False
    generated_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    disclaimer: str = (
        "This brief organizes listing evidence and preferences. It is not legal, financial, "
        "or property-inspection advice; confirm every consequential detail independently."
    )


class CreateDecisionBriefRequest(BaseModel):
    profile_id: str = Field(min_length=1)
    listing_ids: list[str] = Field(min_length=3, max_length=3)
    idempotency_key: str | None = Field(default=None, max_length=120)


class CreateDecisionBriefResponse(BaseModel):
    run: AgentRun
    brief: DecisionBrief | None = None
    reused: bool = False
