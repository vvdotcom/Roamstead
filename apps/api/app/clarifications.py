from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from .agent import agent_enabled, build_clarification_agent
from .data import CANDIDATES
from .listing_fit import score_listing_results
from .listings.catalog import listing_catalog
from .models import (
    AgentEvent,
    AgentRun,
    ClarificationAnswerResponse,
    ClarificationOption,
    ClarificationPlanResponse,
    ClarificationTurn,
    DecisionProfile,
    PreferenceProposal,
)
from .store import store


PREFERENCE_KEYS = (
    "healthcare",
    "remote_work",
    "waterfront",
    "quiet",
    "international_school",
    "food_access",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(
    run: AgentRun,
    sequence: int,
    event_type: str,
    actor: str,
    title: str,
    summary: str,
    public_payload: dict | None = None,
) -> AgentEvent:
    event = AgentEvent(
        id=f"event-{uuid4().hex[:12]}",
        run_id=run.id,
        sequence=sequence,
        event_type=event_type,
        actor=actor,
        title=title,
        summary=summary,
        public_payload=public_payload or {},
    )
    listing_catalog.repository.save_agent_event(event)
    return event


def _mode(profile: DecisionProfile) -> str:
    return "RENT" if any(item.key == "rent_budget" for item in profile.hard_constraints) else "BUY"


def _counterfactual_options(profile: DecisionProfile) -> tuple[int, list[ClarificationOption]]:
    raw = listing_catalog.repository.list(_mode(profile), 100)
    baseline = score_listing_results(raw, profile, CANDIDATES)
    baseline_rank = {item.id: index for index, item in enumerate(baseline[:10], start=1)}
    baseline_score = {item.id: item.fit_score for item in baseline[:10]}
    preferences = {item.key: item for item in profile.preferences}
    candidates: list[tuple[int, ClarificationOption]] = []

    for key in PREFERENCE_KEYS:
        preference = preferences.get(key)
        if not preference or preference.weight >= 0.98:
            continue
        proposed_weight = min(1.0, round(max(preference.weight + 0.20, 0.75), 2))
        simulated = deepcopy(profile)
        next(item for item in simulated.preferences if item.key == key).weight = proposed_weight
        reranked = score_listing_results(raw, simulated, CANDIDATES)
        next_rank = {item.id: index for index, item in enumerate(reranked[:10], start=1)}
        rank_changes = sum(
            baseline_rank.get(listing_id) != next_rank.get(listing_id)
            for listing_id in set(baseline_rank) | set(next_rank)
        )
        score_change = sum(
            abs(next((item.fit_score for item in reranked[:10] if item.id == listing_id), 0) - score)
            for listing_id, score in baseline_score.items()
        )
        leader_changed = bool(baseline and reranked and baseline[0].id != reranked[0].id)
        impact_score = rank_changes * 10 + score_change + (25 if leader_changed else 0)
        impact_summary = (
            f"Would change {rank_changes} positions or memberships across the before-and-after top 10"
            + (" and change the leading match." if leader_changed else ".")
        )
        candidates.append(
            (
                impact_score,
                ClarificationOption(
                    id=f"prefer-{key}",
                    label=preference.label,
                    preference_key=key,
                    proposed_weight=proposed_weight,
                    predicted_top_changes=rank_changes,
                    impact_summary=impact_summary,
                ),
            )
        )

    candidates.sort(key=lambda item: (-item[0], item[1].label))
    options = [item[1] for item in candidates[:2]]
    if len(options) == 2:
        options.append(
            ClarificationOption(
                id="keep-balance",
                label="Keep the current balance",
                impact_summary="Leaves your profile and ranking unchanged.",
            )
        )
    return len(baseline), options


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _agent_result_texts(events: list[object]) -> list[str]:
    """Read either chat text or task-mode finish_task output from public ADK events."""

    texts: list[str] = []
    for event in events:
        content = getattr(event, "content", None)
        for part in (getattr(content, "parts", None) or []):
            value = getattr(part, "text", None)
            if value:
                texts.append(value.strip())
        output = getattr(event, "output", None)
        value = output.get("result") if isinstance(output, dict) else getattr(output, "result", None)
        if value:
            texts.append(str(value).strip())
    return texts


async def _agent_copy(options: list[ClarificationOption], eligible_count: int) -> tuple[str | None, str | None]:
    if not agent_enabled():
        return None, None
    from google.adk.runners import InMemoryRunner

    prompt = json.dumps(
        {
            "eligible_listing_count": eligible_count,
            "options": [
                {
                    "label": option.label,
                    "predicted_top_changes": option.predicted_top_changes,
                    "impact_summary": option.impact_summary,
                }
                for option in options[:2]
            ],
        }
    )
    events = await InMemoryRunner(agent=build_clarification_agent()).run_debug(
        prompt,
        user_id="clarification-planner",
        session_id=f"clarification-{uuid4().hex[:8]}",
        quiet=True,
    )
    texts = _agent_result_texts(events)
    payload = _extract_json(texts[-1]) if texts else None
    if not payload:
        return None, None
    question = re.sub(r"\s+", " ", str(payload.get("question") or "")).strip()[:220]
    why_asked = re.sub(r"\s+", " ", str(payload.get("why_asked") or "")).strip()[:280]
    return (question or None), (why_asked or None)


async def plan_clarification(profile: DecisionProfile) -> ClarificationPlanResponse:
    existing_question = profile.clarifications[-1] if profile.clarifications else None
    if existing_question:
        run = listing_catalog.repository.get_agent_run(existing_question.run_id)
        if run:
            return ClarificationPlanResponse(
                run=run,
                question=existing_question if existing_question.status == "AWAITING_ANSWER" else None,
                events=listing_catalog.repository.list_agent_events(run.id),
                reused=True,
            )

    run = AgentRun(
        id=f"clarification-{uuid4().hex[:12]}",
        profile_id=profile.profile_id,
        run_type="CLARIFICATION",
        status="RUNNING",
        model=os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash"),
        execution_mode="ADK_GEMINI" if agent_enabled() else "VERIFIED_CACHE",
        idempotency_key=f"clarification:{profile.profile_id}:{profile.version}",
    )
    selected_run = listing_catalog.repository.insert_agent_run_if_absent(run)
    if selected_run.id != run.id:
        question = next((item for item in profile.clarifications if item.run_id == selected_run.id), None)
        return ClarificationPlanResponse(
            run=selected_run,
            question=question if question and question.status == "AWAITING_ANSWER" else None,
            events=listing_catalog.repository.list_agent_events(selected_run.id),
            reused=True,
        )

    _event(run, 1, "AGENT_STATUS", "PartnerCoordinator", "Clarification analysis started", "Locked the current profile version and requested a counterfactual ranking check.")
    eligible_count, options = _counterfactual_options(profile)
    _event(
        run,
        2,
        "TOOL_RESULT",
        "CounterfactualRankingTool",
        "High-impact tradeoffs simulated",
        f"Tested approved preference weights against {eligible_count} listings that meet every hard requirement.",
        {"eligible_listings": eligible_count, "candidate_options": [item.model_dump(mode="json") for item in options[:2]]},
    )
    if len(options) < 2:
        run.status = "COMPLETED"
        run.updated_at = _now()
        listing_catalog.repository.save_agent_run(run)
        _event(run, 3, "RUN_COMPLETED", "PartnerCoordinator", "No clarification needed", "The profile did not contain a material unresolved ranking tradeoff.")
        return ClarificationPlanResponse(run=run, events=listing_catalog.repository.list_agent_events(run.id))

    deterministic_question = (
        f"When qualified homes force a tradeoff, should Roamstead favor {options[0].label.lower()} "
        f"or {options[1].label.lower()}?"
    )
    deterministic_reason = (
        f"I checked {eligible_count} listings that meet your hard requirements. "
        f"These two choices would change the largest part of your current top-ten ranking."
    )
    question_text, why_asked = None, None
    if agent_enabled():
        try:
            question_text, why_asked = await _agent_copy(options, eligible_count)
            _event(
                run,
                3,
                "AGENT_STATUS",
                "PreferenceInterpreter",
                "One adaptive question selected",
                "Selected the highest-impact tradeoff calculated from the live profile and saved catalog.",
                {"model": run.model},
            )
        except Exception as exc:
            _event(
                run,
                3,
                "RECOVERABLE_ERROR",
                "PreferenceInterpreter",
                "Adaptive wording unavailable",
                "The ranking analysis supplied the same question without changing profile state.",
                {"error_type": type(exc).__name__},
            )

    question = ClarificationTurn(
        id=f"question-{uuid4().hex[:10]}",
        profile_id=profile.profile_id,
        profile_version=profile.version,
        question=question_text or deterministic_question,
        why_asked=why_asked or deterministic_reason,
        eligible_listing_count=eligible_count,
        options=options,
        run_id=run.id,
    )
    profile.clarifications.append(question)
    store.save_profile(profile)
    _event(
        run,
        4,
        "CLARIFICATION",
        "PartnerCoordinator",
        "Approval-gated clarification ready",
        question.why_asked,
        {"question_id": question.id, "question": question.question, "options": [item.model_dump(mode="json") for item in question.options]},
    )
    listing_catalog.repository.save_agent_run(run)
    return ClarificationPlanResponse(run=run, question=question, events=listing_catalog.repository.list_agent_events(run.id))


def answer_clarification(profile: DecisionProfile, question_id: str, option_id: str) -> ClarificationAnswerResponse:
    question = next((item for item in profile.clarifications if item.id == question_id), None)
    if not question:
        raise LookupError("Clarification question not found")
    if question.status != "AWAITING_ANSWER":
        raise ValueError("Clarification question has already been answered")
    option = next((item for item in question.options if item.id == option_id), None)
    if not option:
        raise ValueError("Choose one of the clarification options")

    question.selected_option_id = option.id
    question.answered_at = _now()
    proposal = None
    events = listing_catalog.repository.list_agent_events(question.run_id)
    sequence = max((event.sequence for event in events), default=0) + 1
    run = listing_catalog.repository.get_agent_run(question.run_id)
    if not run:
        raise LookupError("Clarification run not found")

    if not option.preference_key or option.proposed_weight is None:
        question.status = "NO_CHANGE"
        _event(run, sequence, "TOOL_RESULT", "ProfileStore", "Current balance preserved", "The user kept the existing profile; no preference or ranking changed.")
    else:
        preference = next((item for item in profile.preferences if item.key == option.preference_key), None)
        if not preference:
            raise ValueError("The selected preference is no longer available")
        proposal = PreferenceProposal(
            id=f"proposal-{uuid4().hex[:8]}",
            key=option.preference_key,
            label=option.label,
            rationale=(
                f"You selected {option.label.lower()} after Roamstead simulated its effect on the current qualified listings. "
                "This is still only a proposal; nothing changes until you approve it."
            ),
            evidence_count=max(1, option.predicted_top_changes),
            old_weight=preference.weight,
            proposed_weight=option.proposed_weight,
            source_clarification_id=question.id,
            predicted_impact=option.impact_summary,
        )
        store.save_proposal(profile.profile_id, proposal)
        question.status = "PROPOSAL_CREATED"
        _event(
            run,
            sequence,
            "PROFILE_PROPOSAL",
            "PreferenceInterpreter",
            "Profile change proposed",
            option.impact_summary + " No profile state has changed yet.",
            {"proposal_id": proposal.id, "key": proposal.key, "old_weight": proposal.old_weight, "proposed_weight": proposal.proposed_weight},
        )
    store.save_profile(profile)
    run.status = "COMPLETED"
    run.updated_at = _now()
    listing_catalog.repository.save_agent_run(run)
    _event(run, sequence + 1, "RUN_COMPLETED", "PartnerCoordinator", "Clarification captured", "The answer and its approval state were saved to durable decision memory.")
    return ClarificationAnswerResponse(
        profile=profile,
        question=question,
        proposal=proposal,
        events=listing_catalog.repository.list_agent_events(run.id),
    )
