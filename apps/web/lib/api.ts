export type Preference = {
  key: string;
  label: string;
  weight: number;
  status: string;
};
export type Profile = {
  profile_id: string;
  version: number;
  hard_constraints: {
    key: string;
    label: string;
    operator: string;
    value: string | number;
    locked: boolean;
  }[];
  preferences: Preference[];
  feedback: { id: string; target_id: string; action: string; reason: string }[];
  clarifications: ClarificationTurn[];
};

export type ClarificationOption = {
  id: string;
  label: string;
  preference_key?: string;
  proposed_weight?: number;
  predicted_top_changes: number;
  impact_summary: string;
};

export type ClarificationTurn = {
  id: string;
  profile_id: string;
  profile_version: number;
  question: string;
  why_asked: string;
  eligible_listing_count: number;
  options: ClarificationOption[];
  status: "AWAITING_ANSWER" | "PROPOSAL_CREATED" | "NO_CHANGE";
  selected_option_id?: string;
  run_id: string;
  created_at: string;
  answered_at?: string;
};

export type Candidate = {
  id: string;
  name: string;
  district: string;
  tagline: string;
  image: string;
  score: number;
  rank: number;
  components: {
    budget: number;
    healthcare: number;
    remote_work: number;
    waterfront: number;
    quiet: number;
    international_school: number;
    food_access: number;
  };
  price_from_usd: number;
  rent_from_usd: number;
  hospital_minutes: number;
  waterfront_minutes: number;
  international_school_minutes: number;
  food_minutes: number;
  homes: number;
  map_x: number;
  map_y: number;
  tradeoff: string;
};

export type Listing = {
  id: string;
  neighborhood_id: string;
  title: string;
  transaction_mode: "BUY" | "RENT";
  price_vnd: number;
  price_usd: number;
  price_band: "LOW" | "MEDIUM" | "HIGH" | "ULTRA_HIGH";
  district: string;
  address?: string;
  beds?: number;
  baths?: number;
  area_sqm?: number;
  image_url: string;
  image_urls: string[];
  fit_score: number;
  fit_breakdown: Record<string, number>;
  fit_reasons: string[];
  hospital_minutes?: number;
  waterfront_minutes?: number;
  international_school_minutes_estimate?: number;
  food_minutes_estimate?: number;
  property_type: string;
  source_url: string;
  source_domain: string;
  source_title?: string;
  source_checked_at: string;
  demo: false;
};

export type ListingSearchResult = {
  items: Listing[];
  requested: number;
  returned: number;
  transaction_mode: "BUY" | "RENT";
  live: true;
  partial: boolean;
  minimum_photos_per_listing: number;
  pending_gallery_verification: number;
  searched_at: string;
  provider: string;
  source_domain: string;
  catalog_cached: true;
  last_refreshed_at?: string;
  next_refresh_at?: string;
  storage: string;
};

export type Proposal = {
  id: string;
  key: string;
  label: string;
  rationale: string;
  evidence_count: number;
  old_weight: number;
  proposed_weight: number;
  source_clarification_id?: string;
  predicted_impact?: string;
  status: string;
};

export type Evidence = {
  country: string;
  topic: string;
  status: string;
  summary: string;
  source_title: string;
  source_url: string;
  publisher: string;
  last_checked: string;
  confidence: string;
};

export type Reply = {
  message: string;
  stage: string;
  question?: { id: string; options: { label: string; value: string }[] };
  profile?: Profile;
  recommendations?: Candidate[];
};

export type AgentEvent = {
  id: string;
  run_id: string;
  sequence: number;
  event_type:
    | "CLARIFICATION"
    | "AGENT_STATUS"
    | "TOOL_RESULT"
    | "PROFILE_PROPOSAL"
    | "RECOMMENDATION"
    | "RECOVERABLE_ERROR"
    | "SPECIALIST_STARTED"
    | "SPECIALIST_COMPLETED"
    | "CORRECTION_REQUESTED"
    | "SEMANTIC_MEMORY_STARTED"
    | "SEMANTIC_MEMORY_COMPLETED"
    | "RUN_DEGRADED"
    | "RUN_COMPLETED";
  actor: string;
  title: string;
  summary: string;
  status: string;
  phase?: string;
  model?: string;
  provider?: string;
  duration_ms?: number;
  public_payload: Record<string, unknown>;
  created_at: string;
};

export type EvidenceClaim = {
  id: string;
  listing_id: string;
  label: string;
  value: string;
  status: "CONFIRMED" | "INFERRED" | "UNKNOWN";
  source_url: string;
  observed_at: string;
  explanation: string;
};

export type DecisionBriefProperty = {
  listing_id: string;
  title: string;
  district: string;
  price_usd: number;
  transaction_mode: "BUY" | "RENT";
  fit_score: number;
  fit_reasons: string[];
  image_urls: string[];
  source_url: string;
  source_checked_at: string;
  evidence: EvidenceClaim[];
  tradeoffs: string[];
  verification_questions: string[];
  visual_audit?: PropertyVisualAudit;
};

export type VisualImageAssessment = {
  image_index: number;
  image_url: string;
  classification:
    "INTERIOR" | "EXTERIOR" | "FLOOR_PLAN" | "DOCUMENT" | "UNKNOWN";
  observations: string[];
  warnings: string[];
  confidence: "LOW" | "MEDIUM" | "HIGH";
};

export type PropertyVisualAudit = {
  listing_id: string;
  verdict: "SUPPORTED" | "CHALLENGE" | "INSUFFICIENT";
  images: VisualImageAssessment[];
  unsupported_claims: string[];
  missing_evidence: string[];
  suggested_questions: string[];
};

export type VisualEvidenceAudit = {
  verdict: "SUPPORTED" | "CHALLENGE";
  summary: string;
  properties: PropertyVisualAudit[];
  challenged_claims: string[];
  model: string;
  provider: "GEMINI_API" | "CLOUD_RUN_VLLM";
  analyzed_photo_count: number;
  succeeded: boolean;
  created_at: string;
};

export type MemoryContextMatch = {
  memory_id: string;
  kind: string;
  preference_key?: string;
  text: string;
  target_name?: string;
  city?: string;
  decision_status: string;
  cosine_distance: number;
  created_at: string;
};

export type MemoryContextPacket = {
  query: string;
  matches: MemoryContextMatch[];
  considered_count: number;
  selected_count: number;
  excluded_count: number;
  context_characters: number;
  model: string;
  dimension: number;
  status: "READY" | "UNAVAILABLE";
  error_code?: string;
};

export type MemoryConsistencyAudit = {
  verdict: "CONSISTENT" | "CHALLENGE" | "INSUFFICIENT";
  summary: string;
  relevant_memory_ids: string[];
  conflicting_preferences: string[];
  superseded_preferences: string[];
  unsupported_user_assumptions: string[];
  omitted_tradeoffs: string[];
  suggested_questions: string[];
  model: string;
  provider: "GEMINI_API";
  duration_ms: number;
  succeeded: boolean;
  created_at: string;
};

export type SemanticMemory = {
  id: string;
  source_event_id: string;
  kind: string;
  preference_key?: string;
  source_text: string;
  target_id?: string;
  target_name?: string;
  city?: string;
  transaction_mode?: string;
  decision_status: string;
  embedding_status: string;
  embedding_model: string;
  created_at: string;
};

export type DecisionBrief = {
  run_id: string;
  profile_id: string;
  profile_version: number;
  status: "RUNNING" | "COMPLETED" | "FAILED";
  title: string;
  executive_summary: string;
  properties: DecisionBriefProperty[];
  recommendation: string;
  next_actions: string[];
  unknowns: string[];
  visual_audit?: VisualEvidenceAudit;
  memory_context?: MemoryContextPacket;
  memory_audit?: MemoryConsistencyAudit;
  models_used: string[];
  degraded: boolean;
  generated_at: string;
  disclaimer: string;
};

export type AgentRun = {
  id: string;
  profile_id: string;
  status: string;
  model: string;
  orchestration: string;
  execution_mode: "ADK_GEMINI" | "VERIFIED_CACHE";
  current_stage: string;
  completed_stages: string[];
  models_used: string[];
  degraded: boolean;
};

export type ProfileUpdate = {
  budget_usd: number;
  min_beds: number;
  min_baths: number;
  max_international_school_minutes: number;
  max_food_minutes: number;
  property_types: ("Apartment" | "House")[];
  priorities: Record<string, number>;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(
      payload?.detail ?? `Roamstead API error (${response.status})`,
    );
  }
  return response.json() as Promise<T>;
}

export const api = {
  createSession: (housingMode: "BUY" | "RENT") =>
    request<{
      session: { id: string; profile_id: string; housing_mode: "BUY" | "RENT" };
      profile: Profile;
    }>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ housing_mode: housingMode }),
    }),
  profile: (profileId: string) =>
    request<Profile>(`/api/v1/profiles/${profileId}`),
  updateProfile: (profileId: string, body: ProfileUpdate) =>
    request<{
      profile: Profile;
      recommendations: Candidate[];
      deltas: RankingDelta[];
    }>(`/api/v1/profiles/${profileId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  neighborhoods: (profileId: string) =>
    request<{ items: Candidate[] }>(
      `/api/v1/recommendations/neighborhoods?profile_id=${profileId}`,
    ),
  message: (sessionId: string, body: Record<string, unknown>) =>
    request<Reply>(`/api/v1/sessions/${sessionId}/message`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  feedback: (profileId: string, body: Record<string, unknown>) =>
    request<{
      profile: Profile;
      proposal?: Proposal;
      memory_context?: MemoryContextPacket;
    }>(`/api/v1/profiles/${profileId}/feedback`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  semanticMemory: (profileId: string) =>
    request<SemanticMemory[]>(`/api/v1/profiles/${profileId}/semantic-memory`),
  decide: (profileId: string, proposalId: string, decision: string) =>
    request<{
      profile: Profile;
      recommendations: Candidate[];
      deltas: RankingDelta[];
      explanation: string;
    }>(
      `/api/v1/profiles/${profileId}/preference-proposals/${proposalId}/decision`,
      { method: "POST", body: JSON.stringify({ decision }) },
    ),
  clarification: (profileId: string) =>
    request<{
      run: AgentRun;
      question?: ClarificationTurn;
      events: AgentEvent[];
      reused: boolean;
    }>(`/api/v1/profiles/${profileId}/clarification`, { method: "POST" }),
  answerClarification: (
    profileId: string,
    questionId: string,
    optionId: string,
  ) =>
    request<{
      profile: Profile;
      question: ClarificationTurn;
      proposal?: Proposal;
      events: AgentEvent[];
    }>(`/api/v1/profiles/${profileId}/clarifications/${questionId}/answer`, {
      method: "POST",
      body: JSON.stringify({ option_id: optionId }),
    }),
  undo: (profileId: string) =>
    request<{ profile: Profile; recommendations: Candidate[] }>(
      `/api/v1/profiles/${profileId}/undo`,
      { method: "POST" },
    ),
  listings: (
    transactionMode: "BUY" | "RENT",
    profileId: string,
    focusedNeighborhoodId?: string,
    refresh = false,
  ) =>
    request<ListingSearchResult>("/api/v1/listings/search", {
      method: "POST",
      body: JSON.stringify({
        transaction_mode: transactionMode,
        profile_id: profileId,
        focused_neighborhood_id: focusedNeighborhoodId,
        limit: 100,
        refresh,
      }),
    }),
  evidence: () => request<Evidence>("/api/v1/rule-evidence"),
  save: (profileId: string, itemId: string) =>
    request<{ saved: string[] }>(
      `/api/v1/saved?profile_id=${profileId}&item_id=${itemId}`,
      { method: "POST" },
    ),
  saved: (profileId: string) =>
    request<{ saved: string[] }>(`/api/v1/saved?profile_id=${profileId}`),
  createBrief: (profileId: string, listingIds: string[]) =>
    request<{ run: AgentRun; brief?: DecisionBrief; reused: boolean }>(
      "/api/v1/decision-briefs",
      {
        method: "POST",
        body: JSON.stringify({
          profile_id: profileId,
          listing_ids: listingIds,
        }),
      },
    ),
  brief: (runId: string) =>
    request<DecisionBrief>(`/api/v1/decision-briefs/${runId}`),
  briefs: (profileId: string) =>
    request<{ items: DecisionBrief[] }>(
      `/api/v1/profiles/${profileId}/decision-briefs`,
    ),
  streamBriefEvents: async (
    runId: string,
    onEvent: (event: AgentEvent) => void,
  ) => {
    await new Promise<void>((resolve, reject) => {
      const source = new EventSource(`/agent-stream/${runId}?after=0`);
      let consecutiveErrors = 0;
      const eventNames = [
        "agent_status",
        "tool_result",
        "specialist_started",
        "specialist_completed",
        "semantic_memory_started",
        "semantic_memory_completed",
        "correction_requested",
        "run_degraded",
        "recoverable_error",
        "run_completed",
      ];
      const receive = (message: Event) => {
        try {
          const event = JSON.parse(
            (message as MessageEvent<string>).data,
          ) as AgentEvent;
          consecutiveErrors = 0;
          onEvent(event);
        } catch {
          source.close();
          reject(
            new Error("The agent stream returned a malformed public event."),
          );
        }
      };
      eventNames.forEach((name) => source.addEventListener(name, receive));
      source.addEventListener("stream_end", (message) => {
        source.close();
        const terminal = JSON.parse((message as MessageEvent<string>).data) as {
          status: string;
          error?: string;
        };
        if (terminal.status === "COMPLETED") resolve();
        else
          reject(
            new Error(
              `Decision Brief run failed${terminal.error ? ` (${terminal.error})` : ""}.`,
            ),
          );
      });
      source.onerror = () => {
        consecutiveErrors += 1;
        if (consecutiveErrors < 3) return;
        source.close();
        reject(
          new Error(
            "The live agent stream could not reconnect to its persisted run.",
          ),
        );
      };
    });
  },
  plan: (profileId: string) =>
    request<ActionPlan>(`/api/v1/plans?profile_id=${profileId}`, {
      method: "POST",
    }),
};

export type RankingDelta = {
  candidate_id: string;
  name: string;
  previous_rank: number;
  new_rank: number;
  previous_score: number;
  new_score: number;
};

export type ActionPlan = {
  id: string;
  title: string;
  shortlist: string[];
  steps: { phase: string; task: string }[];
  unresolved_questions: string[];
};
