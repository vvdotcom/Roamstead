from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from time import monotonic
from datetime import datetime, timezone
from uuid import uuid4

from .agent import agent_enabled, build_brief_composer, build_evidence_verifier, build_listing_analyst
from .data import CANDIDATES
from .gemma_critic import (
    VisualImageInput,
    audit_visual_evidence,
    gemma_critic_enabled,
    gemma_model,
    gemma_provider,
    maximum_photos_per_listing,
)
from .listing_fit import score_listing_results
from .listings.catalog import listing_catalog
from .listings.images import available_gallery_size, cached_gallery_paths, public_image_url
from .memory_critic import audit_memory_consistency, memory_critic_enabled, memory_critic_model
from .models import (
    AgentEvent,
    AgentRun,
    CreateDecisionBriefRequest,
    CreateDecisionBriefResponse,
    DecisionBrief,
    DecisionBriefProperty,
    DecisionProfile,
    EvidenceClaim,
    Listing,
    MemoryConsistencyAudit,
    MemoryContextPacket,
    VisualEvidenceAudit,
)
from .semantic_memory import EMBEDDING_MODEL, retrieve_memory


logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionBriefService:
    """Idempotent, durable three-property brief pipeline.

    Deterministic evidence is always composed first. When ADK is enabled, Gemini
    adds a public comparison observation; a provider failure is recoverable and
    never replaces verified catalog facts.
    """

    def __init__(self) -> None:
        self.repository = listing_catalog.repository
        self._tasks: dict[str, asyncio.Task] = {}
        self._task_lock = asyncio.Lock()

    def _key(self, request: CreateDecisionBriefRequest, profile: DecisionProfile) -> str:
        if request.idempotency_key:
            return f"brief:{request.profile_id}:{request.idempotency_key}"
        stable = json.dumps(
            {
                "profile_id": profile.profile_id,
                "profile_version": profile.version,
                "listing_ids": sorted(request.listing_ids),
            },
            sort_keys=True,
        )
        return f"brief:{hashlib.sha256(stable.encode()).hexdigest()}"

    def _event(
        self,
        run: AgentRun,
        sequence: int,
        event_type: str,
        actor: str,
        title: str,
        summary: str,
        public_payload: dict | None = None,
        *,
        status: str = "COMPLETED",
        phase: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        duration_ms: int | None = None,
    ) -> AgentEvent:
        event = AgentEvent(
            id=f"event-{uuid4().hex[:12]}",
            run_id=run.id,
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            title=title,
            summary=summary,
            status=status,
            phase=phase,
            model=model,
            provider=provider,
            duration_ms=duration_ms,
            public_payload=public_payload or {},
        )
        self.repository.save_agent_event(event)
        return event

    @staticmethod
    def _claim(listing: Listing, label: str, value: str, status: str, explanation: str) -> EvidenceClaim:
        return EvidenceClaim(
            id=f"claim-{uuid4().hex[:10]}",
            listing_id=listing.id,
            label=label,
            value=value,
            status=status,
            source_url=listing.source_url,
            observed_at=listing.source_checked_at,
            explanation=explanation,
        )

    def _property(self, listing: Listing) -> DecisionBriefProperty:
        gallery_size = available_gallery_size(listing.id)
        photos = [public_image_url(listing.id, index) for index in range(gallery_size)]
        specs = ", ".join(
            value
            for value in (
                f"{listing.beds} beds" if listing.beds is not None else "",
                f"{listing.baths} baths" if listing.baths is not None else "",
                f"{listing.area_sqm:g} m²" if listing.area_sqm is not None else "",
            )
            if value
        )
        evidence = [
            self._claim(
                listing,
                "Advertised price",
                f"${listing.price_usd:,}{'/month' if listing.transaction_mode == 'RENT' else ''}",
                "CONFIRMED",
                "Confirmed as the normalized advertised price in the saved Batdongsan snapshot; it is not a valuation.",
            ),
            self._claim(
                listing,
                "Reported property details",
                specs or "Not reported",
                "CONFIRMED" if specs else "UNKNOWN",
                "These fields were reported by the listing source and have not been independently measured.",
            ),
            self._claim(
                listing,
                "Verified local photos",
                f"{gallery_size} exact-listing photo{'s' if gallery_size != 1 else ''}",
                "CONFIRMED" if gallery_size else "UNKNOWN",
                "Roamstead serves cached property imagery tied to this listing; public redistribution rights still require confirmation.",
            ),
            self._claim(
                listing,
                "Current availability",
                "Re-check required",
                "UNKNOWN",
                "A saved search snapshot cannot prove that the property remains available now.",
            ),
            self._claim(
                listing,
                "Cross-border eligibility",
                "Property-specific review required",
                "UNKNOWN",
                "The listing does not establish buyer or tenant eligibility, project quota, title, or contract validity.",
            ),
        ]
        tradeoffs: list[str] = []
        if listing.fit_breakdown:
            weakest = sorted(listing.fit_breakdown.items(), key=lambda entry: entry[1])[:2]
            tradeoffs = [f"{key.replace('_', ' ').title()} is the weaker fit ({score}/100)." for key, score in weakest]
        if gallery_size < 3:
            tradeoffs.append(f"Only {gallery_size} verified photo{'s are' if gallery_size != 1 else ' is'} available in the local snapshot.")
        return DecisionBriefProperty(
            listing_id=listing.id,
            title=listing.title,
            district=listing.district,
            price_usd=listing.price_usd,
            transaction_mode=listing.transaction_mode,
            fit_score=listing.fit_score,
            fit_reasons=listing.fit_reasons,
            image_urls=photos,
            source_url=listing.source_url,
            source_checked_at=listing.source_checked_at,
            evidence=evidence,
            tradeoffs=tradeoffs,
            verification_questions=[
                "Is this exact property still available at the advertised USD-equivalent price?",
                "Can the agent provide current authority, ownership or lease documentation and a complete fee schedule?",
                "Which listing claims can be confirmed during a live video tour or independent inspection?",
            ],
        )

    @staticmethod
    def _public_agent_text(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value.replace("**", "")).strip()
        for marker in ("Action Summary:", "Risk Identification:", "Agent Actor:"):
            cleaned = cleaned.split(marker, 1)[0].strip()
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        selected: list[str] = []
        for sentence in (item.strip() for item in sentences[:2] if item.strip()):
            candidate = " ".join([*selected, sentence])
            if len(candidate) > 500:
                break
            selected.append(sentence)
        return " ".join(selected) or cleaned[:497].rstrip() + "..."

    def _next_sequence(self, run_id: str) -> int:
        return max((item.sequence for item in self.repository.list_agent_events(run_id)), default=0) + 1

    def _checkpoint(self, run: AgentRun, stage: str, output: object | None = None, *, model: str | None = None) -> None:
        run.current_stage = stage
        if stage not in run.completed_stages:
            run.completed_stages.append(stage)
        if output is not None:
            if hasattr(output, "model_dump"):
                output = output.model_dump(mode="json")
            run.phase_outputs[stage] = output
        if model and model not in run.models_used:
            run.models_used.append(model)
        run.updated_at = _now()
        self.repository.save_agent_run(run)

    @staticmethod
    def _evidence_packet(properties: list[DecisionBriefProperty]) -> list[dict]:
        return [
            {
                "listing_id": item.listing_id,
                "title": item.title,
                "fit_score": item.fit_score,
                "price_usd": item.price_usd,
                "district": item.district,
                "city": "Ho Chi Minh City",
                "claims": {claim.label: claim.value for claim in item.evidence},
                "confirmed": [claim.value for claim in item.evidence if claim.status == "CONFIRMED"],
                "unknown": [claim.label for claim in item.evidence if claim.status == "UNKNOWN"],
            }
            for item in properties
        ]

    @staticmethod
    def _visual_inputs(properties: list[DecisionBriefProperty]) -> list[VisualImageInput]:
        inputs: list[VisualImageInput] = []
        maximum = maximum_photos_per_listing()
        for item in properties:
            for index, path in enumerate(cached_gallery_paths(item.listing_id)[:maximum]):
                inputs.append(
                    VisualImageInput(
                        listing_id=item.listing_id,
                        image_index=index,
                        image_url=public_image_url(item.listing_id, index),
                        path=path,
                    )
                )
        return inputs

    async def _run_adk_specialist(
        self,
        run: AgentRun,
        *,
        actor: str,
        stage: str,
        agent,
        prompt: str,
        attempt: int,
    ) -> str:
        saved = run.phase_outputs.get(stage)
        if stage in run.completed_stages and isinstance(saved, str) and saved:
            return saved
        from google.adk.runners import InMemoryRunner
        from google.genai import types

        started = monotonic()
        self._event(
            run,
            self._next_sequence(run.id),
            "SPECIALIST_STARTED",
            actor,
            f"{actor} · Gemini started",
            f"{actor} is working inside the PartnerCoordinator ADK run.",
            {"attempt": attempt},
            status="RUNNING",
            phase=stage,
            model=run.model,
            provider="GOOGLE_ADK",
        )
        runner = InMemoryRunner(agent=agent)
        session_id = f"{run.id}-{stage.lower()}-{attempt}"
        await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=run.profile_id,
            session_id=session_id,
        )
        values: list[str] = []
        timeout = float(os.getenv("ADK_SPECIALIST_TIMEOUT_SECONDS", "45"))
        async with asyncio.timeout(timeout):
            async for event in runner.run_async(
                user_id=run.profile_id,
                session_id=session_id,
                new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
            ):
                content = getattr(event, "content", None)
                for part in getattr(content, "parts", []) if content else []:
                    value = getattr(part, "text", None)
                    if value:
                        values.append(value)
                    function_call = getattr(part, "function_call", None)
                    if function_call and getattr(function_call, "name", "") == "finish_task":
                        result = (getattr(function_call, "args", None) or {}).get("result")
                        if isinstance(result, str) and result:
                            values.append(result)
                output = getattr(event, "output", None)
                if isinstance(output, str):
                    values.append(output)
        public_text = self._public_agent_text(" ".join(values))
        if not public_text:
            raise ValueError(f"{actor} returned no public result")
        duration_ms = round((monotonic() - started) * 1000)
        self._event(
            run,
            self._next_sequence(run.id),
            "SPECIALIST_COMPLETED",
            actor,
            f"{actor} · Gemini completed",
            public_text,
            {"attempt": attempt},
            phase=stage,
            model=run.model,
            provider="GOOGLE_ADK",
            duration_ms=duration_ms,
        )
        self._checkpoint(run, stage, public_text, model=run.model)
        return public_text

    async def _run_visual_critic(
        self,
        run: AgentRun,
        *,
        stage: str,
        evidence_packet: list[dict],
        analysis: str,
        images: list[VisualImageInput],
        attempt: int,
    ) -> VisualEvidenceAudit | None:
        saved = run.phase_outputs.get(stage)
        if stage in run.completed_stages and isinstance(saved, dict):
            return VisualEvidenceAudit.model_validate(saved)
        if not gemma_critic_enabled():
            return None
        started = monotonic()
        self._event(
            run,
            self._next_sequence(run.id),
            "SPECIALIST_STARTED",
            "VisualEvidenceCritic",
            "VisualEvidenceCritic · Gemma 4 started",
            f"Gemma 4 is auditing {len(images)} locally served real listing photos and the public Gemini analysis.",
            {"attempt": attempt, "photo_count": len(images)},
            status="RUNNING",
            phase=stage,
            model=gemma_model(),
            provider=gemma_provider(),
        )
        audit = await audit_visual_evidence(evidence_packet, {"ListingAnalyst": analysis}, images)
        if audit is None:
            return None
        duration_ms = round((monotonic() - started) * 1000)
        self._event(
            run,
            self._next_sequence(run.id),
            "SPECIALIST_COMPLETED",
            "VisualEvidenceCritic",
            f"Gemma audited {audit.analyzed_photo_count} real photos · {audit.verdict.title()}",
            audit.summary,
            audit.model_dump(mode="json"),
            phase=stage,
            model=audit.model,
            provider=audit.provider,
            duration_ms=duration_ms,
        )
        self._checkpoint(run, stage, audit, model=audit.model)
        return audit

    async def _run_semantic_memory(
        self,
        run: AgentRun,
        profile: DecisionProfile,
    ) -> MemoryContextPacket:
        stage = "SEMANTIC_MEMORY"
        saved = run.phase_outputs.get(stage)
        if stage in run.completed_stages and isinstance(saved, dict):
            return MemoryContextPacket.model_validate(saved)
        query = "Housing decision preferences and prior property feedback: " + "; ".join(
            f"{item.label} weight {item.weight:.2f}" for item in profile.preferences
        )
        started = monotonic()
        self._event(
            run,
            self._next_sequence(run.id),
            "SEMANTIC_MEMORY_STARTED",
            "SemanticMemoryTool",
            "SemanticMemoryTool · Gemini Embedding started",
            "Searching this profile's durable decision memory for relevant prior feedback and approved decisions.",
            status="RUNNING",
            phase=stage,
            model=EMBEDDING_MODEL,
            provider="GEMINI_API_FIRESTORE",
        )
        packet = await retrieve_memory(self.repository, profile.profile_id, query)
        duration_ms = round((monotonic() - started) * 1000)
        self._event(
            run,
            self._next_sequence(run.id),
            "SEMANTIC_MEMORY_COMPLETED",
            "SemanticMemoryTool",
            f"Retrieved {packet.selected_count} relevant decision memories",
            (
                f"Considered {packet.considered_count} profile-isolated memories and selected "
                f"{packet.selected_count} within the cosine threshold."
                if packet.status == "READY"
                else "Semantic retrieval was unavailable; deterministic profile behavior continues unchanged."
            ),
            packet.model_dump(mode="json"),
            phase=stage,
            model=EMBEDDING_MODEL,
            provider="GEMINI_API_FIRESTORE",
            duration_ms=duration_ms,
        )
        self._checkpoint(run, stage, packet, model=EMBEDDING_MODEL if packet.status == "READY" else None)
        return packet

    async def _run_memory_critic(
        self,
        run: AgentRun,
        *,
        stage: str,
        profile: DecisionProfile,
        memory_context: MemoryContextPacket,
        evidence_packet: list[dict],
        analysis: str,
        visual_audit: VisualEvidenceAudit | None,
        attempt: int,
    ) -> MemoryConsistencyAudit | None:
        saved = run.phase_outputs.get(stage)
        if stage in run.completed_stages and isinstance(saved, dict):
            return MemoryConsistencyAudit.model_validate(saved)
        if not memory_critic_enabled():
            return None
        self._event(
            run,
            self._next_sequence(run.id),
            "SPECIALIST_STARTED",
            "MemoryConsistencyCritic",
            "MemoryConsistencyCritic · Gemma 4 31B started",
            "Gemma is checking the public comparison against approved preferences and compact retrieved decision memory.",
            {"attempt": attempt, "memory_count": memory_context.selected_count},
            status="RUNNING",
            phase=stage,
            model=memory_critic_model(),
            provider="GEMINI_API",
        )
        audit = await audit_memory_consistency(
            profile=profile.model_dump(mode="json"),
            memory_context=memory_context,
            evidence_packet=evidence_packet,
            listing_analysis=analysis,
            visual_audit=visual_audit.model_dump(mode="json") if visual_audit else None,
        )
        if audit is None:
            return None
        self._event(
            run,
            self._next_sequence(run.id),
            "SPECIALIST_COMPLETED",
            "MemoryConsistencyCritic",
            f"Memory audit · {audit.verdict.title()}",
            audit.summary,
            audit.model_dump(mode="json"),
            phase=stage,
            model=audit.model,
            provider=audit.provider,
            duration_ms=audit.duration_ms,
        )
        self._checkpoint(run, stage, audit, model=audit.model)
        return audit

    async def _agent_pipeline(
        self, run: AgentRun, profile: DecisionProfile, properties: list[DecisionBriefProperty]
    ) -> tuple[str | None, VisualEvidenceAudit | None, MemoryContextPacket, MemoryConsistencyAudit | None, bool]:
        memory_context = await self._run_semantic_memory(run, profile)
        if not agent_enabled():
            run.degraded = True
            self.repository.save_agent_run(run)
            return None, None, memory_context, None, True

        packet = self._evidence_packet(properties)
        images = self._visual_inputs(properties)
        degraded = False
        audit: VisualEvidenceAudit | None = None
        memory_audit: MemoryConsistencyAudit | None = None
        if memory_context.status != "READY":
            degraded = True
            run.degraded = True
            self._event(
                run,
                self._next_sequence(run.id),
                "RUN_DEGRADED",
                "SemanticMemoryTool",
                "Semantic memory unavailable",
                "The brief continues from the approved profile and deterministic evidence, but this run does not prove embedding integration.",
                phase="SEMANTIC_MEMORY",
                model=EMBEDDING_MODEL,
                provider="GEMINI_API_FIRESTORE",
            )
            self.repository.save_agent_run(run)
        try:
            analysis = await self._run_adk_specialist(
                run,
                actor="ListingAnalyst",
                stage="LISTING_ANALYSIS_1",
                agent=build_listing_analyst(),
                prompt=(
                    "Analyze these three listings using only the deterministic packet and approved profile. Retrieved memory is "
                    "advisory context, never a hard requirement: "
                    + json.dumps({"evidence": packet, "profile": profile.model_dump(mode="json"), "memory": memory_context.model_dump(mode="json")})
                ),
                attempt=1,
            )
            try:
                audit = await self._run_visual_critic(
                    run,
                    stage="VISUAL_AUDIT_1",
                    evidence_packet=packet,
                    analysis=analysis,
                    images=images,
                    attempt=1,
                )
                if audit is None:
                    degraded = True
                    run.degraded = True
                    self._event(
                        run,
                        self._next_sequence(run.id),
                        "RUN_DEGRADED",
                        "VisualEvidenceCritic",
                        "Gemma visual audit not configured",
                        "This brief can continue from deterministic evidence but does not count as a successful additional-model run.",
                        phase="VISUAL_AUDIT_1",
                        model=gemma_model(),
                        provider=gemma_provider(),
                    )
                    self.repository.save_agent_run(run)
            except Exception as exc:
                degraded = True
                run.degraded = True
                self._event(
                    run,
                    self._next_sequence(run.id),
                    "RUN_DEGRADED",
                    "VisualEvidenceCritic",
                    "Gemma visual audit unavailable",
                    "The brief will retain deterministic evidence but cannot claim a successful Gemma integration for this run.",
                    {"error_type": type(exc).__name__},
                    phase="VISUAL_AUDIT_1",
                    model=gemma_model(),
                    provider=gemma_provider(),
                )
                self.repository.save_agent_run(run)

            try:
                memory_audit = await self._run_memory_critic(
                    run,
                    stage="MEMORY_CONSISTENCY_1",
                    profile=profile,
                    memory_context=memory_context,
                    evidence_packet=packet,
                    analysis=analysis,
                    visual_audit=audit,
                    attempt=1,
                )
                if memory_audit is None:
                    degraded = True
                    run.degraded = True
                    self._event(
                        run,
                        self._next_sequence(run.id),
                        "RUN_DEGRADED",
                        "MemoryConsistencyCritic",
                        "Gemma memory audit not configured",
                        "The brief continues from deterministic evidence but this run does not prove the Gemma 31B integration.",
                        phase="MEMORY_CONSISTENCY_1",
                        model=memory_critic_model(),
                        provider="GEMINI_API",
                    )
                    self.repository.save_agent_run(run)
            except Exception as exc:
                degraded = True
                run.degraded = True
                self._event(
                    run,
                    self._next_sequence(run.id),
                    "RUN_DEGRADED",
                    "MemoryConsistencyCritic",
                    "Gemma memory audit unavailable",
                    "The approved profile remains authoritative; this run cannot claim a successful Gemma 31B audit.",
                    {"error_type": type(exc).__name__},
                    phase="MEMORY_CONSISTENCY_1",
                    model=memory_critic_model(),
                    provider="GEMINI_API",
                )
                self.repository.save_agent_run(run)

            verification_prompt = json.dumps(
                {
                    "deterministic_evidence": packet,
                    "listing_analysis": analysis,
                    "visual_audit": audit.model_dump(mode="json") if audit else None,
                    "memory_context": memory_context.model_dump(mode="json"),
                    "memory_audit": memory_audit.model_dump(mode="json") if memory_audit else None,
                }
            )
            verification = await self._run_adk_specialist(
                run,
                actor="EvidenceVerifier",
                stage="EVIDENCE_VERIFICATION_1",
                agent=build_evidence_verifier(),
                prompt=verification_prompt,
                attempt=1,
            )

            correction_needed = (
                bool(audit and audit.verdict == "CHALLENGE")
                or bool(memory_audit and memory_audit.verdict == "CHALLENGE")
                or verification.casefold().startswith("revise")
            )
            if correction_needed:
                challenged = audit.challenged_claims if audit else []
                memory_challenges = (
                    [
                        *memory_audit.unsupported_user_assumptions,
                        *memory_audit.omitted_tradeoffs,
                        *memory_audit.conflicting_preferences,
                    ]
                    if memory_audit
                    else []
                )
                feedback = " ".join([verification, *challenged, *memory_challenges])
                if "CORRECTION_REQUESTED" not in run.completed_stages:
                    self._event(
                        run,
                        self._next_sequence(run.id),
                        "CORRECTION_REQUESTED",
                        "PartnerCoordinator",
                        "One bounded correction requested",
                        "Gemma or EvidenceVerifier found unsupported language; the coordinator is rerunning analysis once without changing evidence or profile state.",
                        {"max_corrections": 1, "challenged_claims": challenged, "memory_challenges": memory_challenges},
                        status="RUNNING",
                        phase="CORRECTION",
                        model=run.model,
                        provider="GOOGLE_ADK",
                    )
                    self._checkpoint(run, "CORRECTION_REQUESTED", {"feedback": feedback})
                analysis = await self._run_adk_specialist(
                    run,
                    actor="ListingAnalyst",
                    stage="LISTING_ANALYSIS_2",
                    agent=build_listing_analyst(),
                    prompt=(
                        "This is the only correction pass. Remove all challenged language, use exact packet values only, "
                        "and keep consequential unknowns explicit. Feedback: " + feedback + " Packet: " + json.dumps(packet)
                    ),
                    attempt=2,
                )
                if not degraded:
                    audit = await self._run_visual_critic(
                        run,
                        stage="VISUAL_AUDIT_2",
                        evidence_packet=packet,
                        analysis=analysis,
                        images=images,
                        attempt=2,
                    )
                if memory_critic_enabled():
                    memory_audit = await self._run_memory_critic(
                        run,
                        stage="MEMORY_CONSISTENCY_2",
                        profile=profile,
                        memory_context=memory_context,
                        evidence_packet=packet,
                        analysis=analysis,
                        visual_audit=audit,
                        attempt=2,
                    )
                verification = await self._run_adk_specialist(
                    run,
                    actor="EvidenceVerifier",
                    stage="EVIDENCE_VERIFICATION_2",
                    agent=build_evidence_verifier(),
                    prompt=json.dumps(
                        {
                            "deterministic_evidence": packet,
                            "corrected_listing_analysis": analysis,
                            "visual_audit": audit.model_dump(mode="json") if audit else None,
                            "memory_context": memory_context.model_dump(mode="json"),
                            "memory_audit": memory_audit.model_dump(mode="json") if memory_audit else None,
                        }
                    ),
                    attempt=2,
                )
                correction_cleared = not (
                    (audit and audit.verdict == "CHALLENGE")
                    or (memory_audit and memory_audit.verdict == "CHALLENGE")
                    or verification.casefold().startswith("revise")
                )
                self._event(
                    run,
                    self._next_sequence(run.id),
                    "TOOL_RESULT",
                    "PartnerCoordinator",
                    "Bounded correction completed",
                    "The only permitted correction pass completed; no profile, score, or deterministic evidence changed.",
                    {"corrections_used": 1, "challenge_cleared": correction_cleared},
                    phase="CORRECTION",
                    provider="GOOGLE_ADK",
                )
                if not correction_cleared:
                    degraded = True
                    run.degraded = True
                    self._event(
                        run,
                        self._next_sequence(run.id),
                        "RUN_DEGRADED",
                        "PartnerCoordinator",
                        "Unsupported language removed from final brief",
                        "The bounded correction did not clear every challenge, so the final summary will use deterministic evidence only.",
                        {"corrections_used": 1},
                        phase="CORRECTION",
                    )
                    self.repository.save_agent_run(run)

            if degraded and verification.casefold().startswith("revise"):
                return None, audit, memory_context, memory_audit, True
            summary = await self._run_adk_specialist(
                run,
                actor="BriefComposer",
                stage="BRIEF_COMPOSITION",
                agent=build_brief_composer(),
                prompt=json.dumps(
                    {
                        "deterministic_evidence": packet,
                        "listing_analysis": analysis,
                        "visual_audit": audit.model_dump(mode="json") if audit else None,
                        "memory_context": memory_context.model_dump(mode="json"),
                        "memory_audit": memory_audit.model_dump(mode="json") if memory_audit else None,
                        "verification": verification,
                    }
                ),
                attempt=1,
            )
            return summary, audit, memory_context, memory_audit, degraded
        except Exception as exc:
            logger.exception("ADK Decision Brief workflow degraded for run %s", run.id)
            degraded = True
            run.degraded = True
            self._event(
                run,
                self._next_sequence(run.id),
                "RUN_DEGRADED",
                "PartnerCoordinator",
                "ADK specialist workflow degraded",
                "The verified-cache brief continued without unsupported model-written conclusions.",
                {"error_type": type(exc).__name__},
                phase=run.current_stage,
                model=run.model,
                provider="GOOGLE_ADK",
            )
            self.repository.save_agent_run(run)
            return None, audit, memory_context, memory_audit, degraded

    async def create(self, request: CreateDecisionBriefRequest, profile: DecisionProfile) -> CreateDecisionBriefResponse:
        """Persist a queued run and return before any specialist starts."""
        if len(set(request.listing_ids)) != 3:
            raise ValueError("Choose three different properties for a Decision Brief")
        key = self._key(request, profile)
        existing_run = self.repository.get_agent_run_by_key(key)
        if existing_run:
            existing_brief = self.repository.get_decision_brief(existing_run.id)
            return CreateDecisionBriefResponse(run=existing_run, brief=existing_brief, reused=True)

        raw_items = [listing_catalog.get(listing_id) for listing_id in request.listing_ids]
        if any(item is None for item in raw_items):
            raise LookupError("One or more selected properties are no longer in the verified catalog")
        listings = [item for item in raw_items if item is not None]
        if len({item.transaction_mode for item in listings}) != 1:
            raise ValueError("All three properties must use the same buy or rent flow")

        run = AgentRun(
            id=f"brief-{uuid4().hex[:12]}",
            profile_id=profile.profile_id,
            run_type="DECISION_BRIEF",
            status="QUEUED",
            model=os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash"),
            execution_mode="ADK_GEMINI" if agent_enabled() else "VERIFIED_CACHE",
            idempotency_key=key,
            input_payload={
                "listing_ids": request.listing_ids,
                "profile": profile.model_dump(mode="json"),
            },
        )
        selected_run = self.repository.insert_agent_run_if_absent(run)
        if selected_run.id != run.id:
            existing_brief = self.repository.get_decision_brief(selected_run.id)
            return CreateDecisionBriefResponse(run=selected_run, brief=existing_brief, reused=True)
        return CreateDecisionBriefResponse(run=run)

    async def ensure_execution(self, run_id: str) -> asyncio.Task | None:
        run = self.repository.get_agent_run(run_id)
        if not run:
            raise LookupError("Agent run not found")
        if run.status == "COMPLETED" and self.repository.get_decision_brief(run_id):
            return None
        async with self._task_lock:
            active = self._tasks.get(run_id)
            if active and not active.done():
                return active
            task = asyncio.create_task(self._execute_guarded(run_id), name=f"decision-brief-{run_id}")
            self._tasks[run_id] = task
            return task

    async def _execute_guarded(self, run_id: str) -> DecisionBrief | None:
        try:
            return await self.execute(run_id)
        except Exception as exc:
            run = self.repository.get_agent_run(run_id)
            if run:
                sequence = max((item.sequence for item in self.repository.list_agent_events(run.id)), default=0) + 1
                self._event(
                    run,
                    sequence,
                    "RECOVERABLE_ERROR",
                    "PartnerCoordinator",
                    "Decision Brief run failed",
                    "The saved run can be retried without inventing or replacing listing evidence.",
                    {"error_type": type(exc).__name__, "terminal": True},
                )
                run.status = "FAILED"
                run.error = type(exc).__name__
                run.updated_at = _now()
                self.repository.save_agent_run(run)
            return None

    async def execute(self, run_id: str) -> DecisionBrief:
        """Run a queued brief while the connected SSE request keeps Cloud Run active."""
        run = self.repository.get_agent_run(run_id)
        if not run:
            raise LookupError("Agent run not found")
        existing = self.repository.get_decision_brief(run.id)
        if existing and run.status == "COMPLETED":
            return existing
        try:
            profile = DecisionProfile.model_validate(run.input_payload["profile"])
            listing_ids = list(run.input_payload["listing_ids"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("The saved agent run is missing its resumable input snapshot") from exc

        run.status = "RUNNING"
        run.error = None
        run.started_at = run.started_at or _now()
        run.current_stage = "STARTING"
        run.updated_at = _now()
        self.repository.save_agent_run(run)
        sequence = max((item.sequence for item in self.repository.list_agent_events(run.id)), default=0) + 1
        self._event(
            run,
            sequence,
            "AGENT_STATUS",
            "PartnerCoordinator",
            "Decision Brief started" if sequence == 1 else "Decision Brief resumed",
            "Locked the saved profile version and three selected listing IDs for this run.",
            {"phase": "RUNNING", "profile_version": profile.version},
            status="RUNNING",
            phase="PROFILE_LOCK",
            provider="DATABASE",
        )

        raw_items = [listing_catalog.get(listing_id) for listing_id in listing_ids]
        if any(item is None for item in raw_items):
            raise LookupError("One or more selected properties are no longer in the verified catalog")
        listings = [item for item in raw_items if item is not None]
        saved_properties = run.phase_outputs.get("DETERMINISTIC_EVIDENCE")
        if "DETERMINISTIC_EVIDENCE" in run.completed_stages and isinstance(saved_properties, list):
            properties = [DecisionBriefProperty.model_validate(item) for item in saved_properties]
        else:
            scored = score_listing_results(listings, profile, CANDIDATES)
            sequence = self._next_sequence(run.id)
            self._event(
                run,
                sequence,
                "TOOL_RESULT",
                "FitScoreTool",
                "Profile fit recalculated",
                "Deterministic Fit Scores were recalculated from the saved Decision Profile.",
                {"scores": {item.id: item.fit_score for item in scored}},
                phase="FIT_SCORE",
                provider="DETERMINISTIC_TOOL",
            )
            properties = [self._property(item) for item in scored]
            self._event(
                run,
                self._next_sequence(run.id),
                "TOOL_RESULT",
                "ListingSnapshotTool",
                "Listing evidence packet prepared",
                "Compared English titles, USD prices, reported specifications, and verified local galleries.",
                {"real_listing_count": len(properties), "local_photo_count": sum(len(item.image_urls) for item in properties)},
                phase="EVIDENCE_PACKET",
                provider="DATABASE",
            )
            unknown_count = sum(claim.status == "UNKNOWN" for item in properties for claim in item.evidence)
            self._event(
                run,
                self._next_sequence(run.id),
                "TOOL_RESULT",
                "EvidenceRulesTool",
                "Deterministic evidence labels checked",
                f"Marked source-backed facts and retained {unknown_count} consequential unknowns for human verification.",
                {"unknown_claims": unknown_count},
                phase="EVIDENCE_PACKET",
                provider="DETERMINISTIC_TOOL",
            )
            self._checkpoint(run, "DETERMINISTIC_EVIDENCE", [item.model_dump(mode="json") for item in properties])

        observation, visual_audit, memory_context, memory_audit, degraded = await self._agent_pipeline(run, profile, properties)
        if visual_audit:
            audits = {item.listing_id: item for item in visual_audit.properties}
            properties = [
                item.model_copy(
                    update={
                        "visual_audit": audits.get(item.listing_id),
                        "verification_questions": list(
                            dict.fromkeys(
                                [
                                    *item.verification_questions,
                                    *(audits[item.listing_id].suggested_questions if item.listing_id in audits else []),
                                ]
                            )
                        ),
                    }
                )
                for item in properties
            ]
        best = properties[0]
        executive_summary = (
            observation
            or f"{best.title} currently leads this three-property comparison at {best.fit_score}/100. "
            "The ranking uses your approved profile; availability and transaction eligibility remain unknown until independently verified."
        )
        brief = DecisionBrief(
            run_id=run.id,
            profile_id=profile.profile_id,
            profile_version=profile.version,
            status="COMPLETED",
            executive_summary=executive_summary,
            properties=properties,
            recommendation=(
                f"Use {best.title} as the first verification call because it has the strongest current profile fit. "
                "Keep all three options open until source availability, complete costs, and property-specific documentation are confirmed."
            ),
            next_actions=[
                "Open each original Batdongsan page and capture current availability, price, agent identity, and timestamp.",
                "Request a live video tour covering the exact unit, view, building access, defects, and every advertised room.",
                "Have an independent qualified local professional review ownership or lease authority, contract terms, fees, and eligibility before any payment.",
            ],
            unknowns=[
                "Current availability and whether the advertised price is still honored.",
                "The identity and authority of the seller, landlord, or listing agent.",
                "Property-specific legal eligibility, title or lease validity, total fees, defects, and photo recency.",
            ],
            visual_audit=visual_audit,
            memory_context=memory_context,
            memory_audit=memory_audit,
            models_used=run.models_used,
            degraded=degraded or run.degraded,
        )
        self.repository.save_decision_brief(brief)
        completion_sequence = max((item.sequence for item in self.repository.list_agent_events(run.id)), default=0) + 1
        self._event(
            run,
            completion_sequence,
            "RUN_COMPLETED",
            "DatabaseWriter",
            "Decision Brief ready",
            "Saved the comparison, live agent trace, Gemma visual audit, evidence claims, questions, and next actions to the durable database.",
            {"brief_run_id": run.id, "models_used": run.models_used, "degraded": brief.degraded},
            phase="DATABASE_SAVE",
            provider="DATABASE",
        )
        if "DATABASE_SAVE" not in run.completed_stages:
            run.completed_stages.append("DATABASE_SAVE")
        run.status = "COMPLETED"
        run.current_stage = "COMPLETED"
        run.completed_at = _now()
        run.updated_at = _now()
        self.repository.save_agent_run(run)
        return brief


decision_brief_service = DecisionBriefService()
