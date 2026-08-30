from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from .agent import agent_enabled, build_due_diligence_planner
from .cloud import cloud_listing_image_count
from .listings.images import available_gallery_size
from .listings.repository import ListingRepository
from .models import (
    CreateDecisionWatchRequest,
    DecisionProfile,
    DecisionWatch,
    DecisionWatchEvent,
    DecisionWatchResponse,
    DueDiligencePlan,
    DueDiligenceTask,
    EvidenceObservation,
    EvidenceRevision,
    Listing,
)


TOOL_ORDER = {
    "SOURCE_AVAILABILITY": 0,
    "PRICE_COMPARISON": 1,
    "PHOTO_EVIDENCE": 2,
    "CURRENCY_NORMALIZATION": 3,
    "PROXIMITY_VERIFICATION": 4,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _event_id(watch_id: str, sequence: int) -> str:
    return f"watch-event-{hashlib.sha256(f'{watch_id}:{sequence}'.encode()).hexdigest()[:20]}"


def _task_id(listing_id: str, tool: str) -> str:
    return f"task-{hashlib.sha256(f'{listing_id}:{tool}'.encode()).hexdigest()[:16]}"


def _constraint(profile: DecisionProfile, key: str, default: int) -> int:
    item = next((value for value in profile.hard_constraints if value.key == key), None)
    try:
        return int(item.value) if item else default
    except (TypeError, ValueError):
        return default


def _photo_count(listing_id: str) -> int:
    local_count = available_gallery_size(listing_id)
    if local_count:
        return local_count
    try:
        return cloud_listing_image_count(listing_id)
    except Exception:
        return 0


def _candidate(
    listing: Listing,
    tool: str,
    reason: str,
    priority: int,
    baseline_value: str,
    baseline_status: str,
    *,
    observed_at: str | None = None,
) -> DueDiligenceTask:
    return DueDiligenceTask(
        id=_task_id(listing.id, tool),
        listing_id=listing.id,
        tool=tool,
        reason=reason,
        priority=priority,
        baseline_value=baseline_value,
        baseline_status=baseline_status,
        source_url=listing.source_url,
        baseline_observed_at=observed_at or listing.source_checked_at,
    )


def _planner_candidates(profile: DecisionProfile, listings: list[Listing]) -> list[DueDiligenceTask]:
    budget_key = "rent_budget" if listings[0].transaction_mode == "RENT" else "budget"
    budget = _constraint(profile, budget_key, 0)
    school_limit = _constraint(profile, "max_international_school_minutes", 30)
    food_limit = _constraint(profile, "max_food_minutes", 15)
    vnd_per_usd = max(1, int(os.getenv("VND_PER_USD", "26000")))
    tasks: list[DueDiligenceTask] = []

    for listing in listings:
        tasks.append(
            _candidate(
                listing,
                "SOURCE_AVAILABILITY",
                "Recheck whether the exact Batdongsan source page is still reachable; reachability never proves availability.",
                5,
                f"Source captured from {listing.source_domain}; current availability is unverified.",
                "UNKNOWN",
            )
        )
        price_pressure = bool(budget and listing.price_usd >= budget * 0.8)
        tasks.append(
            _candidate(
                listing,
                "PRICE_COMPARISON",
                "Recheck the source's advertised price because this property uses a material share of the approved budget."
                if price_pressure
                else "Compare the latest source-advertised price with the saved real-data snapshot.",
                5 if price_pressure else 3,
                f"VND {listing.price_vnd:,} / USD {listing.price_usd:,}",
                "CONFIRMED",
            )
        )
        photos = _photo_count(listing.id)
        if photos < 3:
            tasks.append(
                _candidate(
                    listing,
                    "PHOTO_EVIDENCE",
                    f"Only {photos} exact-listing photo{'s are' if photos != 1 else ' is'} cached, so visual support is limited.",
                    5,
                    f"{photos} cached exact-listing photo{'s' if photos != 1 else ''}",
                    "CONFIRMED" if photos else "UNKNOWN",
                )
            )
        normalized = round(listing.price_vnd / vnd_per_usd)
        if normalized != listing.price_usd:
            tasks.append(
                _candidate(
                    listing,
                    "CURRENCY_NORMALIZATION",
                    "The stored USD display differs from the configured deterministic VND conversion and should be rechecked.",
                    4,
                    f"USD {listing.price_usd:,} at the saved normalization",
                    "INFERRED",
                )
            )
        school = listing.international_school_minutes_estimate
        food = listing.food_minutes_estimate
        proximity_gap = school is None or food is None
        close_to_limit = (
            school is not None
            and abs(school - school_limit) <= 5
            or food is not None
            and abs(food - food_limit) <= 3
        )
        if proximity_gap or close_to_limit:
            tasks.append(
                _candidate(
                    listing,
                    "PROXIMITY_VERIFICATION",
                    "A school or daily-needs estimate is missing or close to the approved travel-time limit.",
                    4,
                    f"School estimate: {school if school is not None else 'unknown'} min; food estimate: {food if food is not None else 'unknown'} min",
                    "INFERRED" if not proximity_gap else "UNKNOWN",
                )
            )
    return tasks


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _agent_texts(events: list[object]) -> list[str]:
    texts: list[str] = []
    for event in events:
        content = getattr(event, "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "text", None):
                texts.append(str(part.text).strip())
        output = getattr(event, "output", None)
        result = output.get("result") if isinstance(output, dict) else getattr(output, "result", None)
        if result:
            texts.append(str(result).strip())
    return texts


async def _model_selection(
    profile: DecisionProfile,
    listings: list[Listing],
    candidates: list[DueDiligenceTask],
) -> tuple[list[str], str] | None:
    if not agent_enabled():
        return None
    from google.adk.runners import InMemoryRunner

    payload = {
        "profile_version": profile.version,
        "listings": [
            {
                "id": listing.id,
                "district": listing.district,
                "transaction_mode": listing.transaction_mode,
                "price_usd": listing.price_usd,
                "fit_score": listing.fit_score,
            }
            for listing in listings
        ],
        "candidate_tasks": [
            {
                "id": task.id,
                "listing_id": task.listing_id,
                "tool": task.tool,
                "reason": task.reason,
                "priority": task.priority,
                "baseline_status": task.baseline_status,
            }
            for task in candidates
        ],
    }
    events = await InMemoryRunner(agent=build_due_diligence_planner()).run_debug(
        json.dumps(payload),
        user_id=f"watch-planner-{profile.profile_id}",
        session_id=f"watch-plan-{uuid4().hex[:10]}",
        quiet=True,
    )
    texts = _agent_texts(events)
    result = _extract_json(texts[-1]) if texts else None
    if not result:
        return None
    selected = result.get("selected_task_ids")
    summary = re.sub(r"\s+", " ", str(result.get("public_summary") or "")).strip()[:500]
    if not isinstance(selected, list) or not summary:
        return None
    return [str(task_id) for task_id in selected], summary


def _bounded_tasks(
    candidates: list[DueDiligenceTask], selected_ids: list[str] | None
) -> list[DueDiligenceTask]:
    by_id = {task.id: task for task in candidates}
    selected = [by_id[task_id] for task_id in selected_ids or [] if task_id in by_id]
    for listing_id in dict.fromkeys(task.listing_id for task in candidates):
        source = next(
            task
            for task in candidates
            if task.listing_id == listing_id and task.tool == "SOURCE_AVAILABILITY"
        )
        if all(task.id != source.id for task in selected):
            selected.append(source)
        if not any(task.listing_id == listing_id and task.tool != "SOURCE_AVAILABILITY" for task in selected):
            alternative = sorted(
                [task for task in candidates if task.listing_id == listing_id and task.tool != "SOURCE_AVAILABILITY"],
                key=lambda task: (-task.priority, TOOL_ORDER[task.tool]),
            )
            if alternative:
                selected.append(alternative[0])
    unique = {task.id: task for task in selected}
    return sorted(unique.values(), key=lambda task: (task.listing_id, TOOL_ORDER[task.tool]))[:9]


def _fallback_summary(tasks: list[DueDiligenceTask]) -> str:
    tools = sorted({task.tool.replace("_", " ").lower() for task in tasks})
    return (
        "Roamstead selected a bounded watch for the three properties: "
        + ", ".join(tools)
        + ". The plan is saved but will not run until you approve it."
    )


def _extract_source_price(html: str) -> int | None:
    patterns = (
        r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|price)["\'][^>]+content=["\']([0-9.,]+)',
        r'"price"\s*:\s*"?([0-9]{6,15})"?',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if not match:
            continue
        digits = re.sub(r"[^0-9]", "", match.group(1))
        if digits:
            value = int(digits)
            if value >= 100_000:
                return value
    return None


async def _fetch_source(url: str) -> tuple[int | None, str]:
    timeout = float(os.getenv("ROAMSTEAD_WATCH_HTTP_TIMEOUT_SECONDS", "8"))
    headers = {"User-Agent": "RoamsteadEvidenceWatch/1.0 (+source-verification)"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
        return response.status_code, response.text[:1_000_000]
    except httpx.HTTPError:
        return None, ""


class DecisionWatchService:
    def __init__(self, repository: ListingRepository | None = None) -> None:
        self.repository = repository or ListingRepository()

    def _events(self, watch_id: str) -> list[DecisionWatchEvent]:
        return self.repository.list_decision_watch_events(watch_id)

    def _event(
        self,
        watch_id: str,
        event_type: str,
        title: str,
        summary: str,
        payload: dict | None = None,
    ) -> DecisionWatchEvent:
        sequence = max((event.sequence for event in self._events(watch_id)), default=0) + 1
        event = DecisionWatchEvent(
            id=_event_id(watch_id, sequence),
            watch_id=watch_id,
            sequence=sequence,
            event_type=event_type,
            title=title,
            summary=summary,
            public_payload=payload or {},
        )
        self.repository.save_decision_watch_event(event)
        return event

    def response(self, watch: DecisionWatch, *, reused: bool = False) -> DecisionWatchResponse:
        return DecisionWatchResponse(
            watch=watch,
            revisions=self.repository.list_evidence_revisions(watch.id),
            events=self._events(watch.id),
            reused=reused,
        )

    async def create(
        self, request: CreateDecisionWatchRequest, profile: DecisionProfile
    ) -> DecisionWatchResponse:
        listing_ids = list(dict.fromkeys(request.listing_ids))
        if len(listing_ids) != 3:
            raise ValueError("Choose exactly three different properties")
        listings = [self.repository.get(listing_id) for listing_id in listing_ids]
        if any(listing is None for listing in listings):
            raise LookupError("Every watched property must exist in the verified real-data catalog")
        verified = [listing for listing in listings if listing is not None]
        if any(listing.source_domain != "batdongsan.com.vn" or listing.demo for listing in verified):
            raise ValueError("Decision Watch accepts only real Batdongsan catalog properties")

        key = request.idempotency_key or hashlib.sha256(
            f"{profile.profile_id}:{profile.version}:{':'.join(sorted(listing_ids))}".encode()
        ).hexdigest()[:32]
        existing = self.repository.get_decision_watch_by_key(key)
        if existing:
            return self.response(existing, reused=True)

        candidates = _planner_candidates(profile, verified)
        model_result = None
        if agent_enabled():
            try:
                model_result = await _model_selection(profile, verified, candidates)
            except Exception:
                model_result = None
        selected_ids, summary = model_result or ([], "")
        tasks = _bounded_tasks(candidates, selected_ids)
        degraded = model_result is None
        if not summary:
            summary = _fallback_summary(tasks)
        model = os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash")
        watch_id = f"watch-{hashlib.sha256(key.encode()).hexdigest()[:16]}"
        plan = DueDiligencePlan(
            id=f"plan-{hashlib.sha256(f'{watch_id}:{profile.version}'.encode()).hexdigest()[:16]}",
            profile_id=profile.profile_id,
            profile_version=profile.version,
            listing_ids=listing_ids,
            tasks=tasks,
            public_summary=summary,
            model=model,
            provider="GOOGLE_ADK" if not degraded else "DETERMINISTIC_FALLBACK",
            degraded=degraded,
        )
        watch = DecisionWatch(
            id=watch_id,
            idempotency_key=key,
            profile_id=profile.profile_id,
            listing_ids=listing_ids,
            plan=plan,
        )
        selected = self.repository.insert_decision_watch_if_absent(watch)
        if selected.id != watch.id:
            return self.response(selected, reused=True)
        self._event(
            watch.id,
            "PLAN_CREATED",
            "Approval-ready watch plan created",
            "The planner selected property-specific checks. No scheduled action has started.",
            {
                "planner": "DueDiligencePlanner",
                "model": plan.model,
                "provider": plan.provider,
                "task_count": len(tasks),
                "tools": sorted({task.tool for task in tasks}),
                "approval_required": True,
            },
        )
        return self.response(watch)

    async def approve(self, watch_id: str, *, run_now: bool = True) -> DecisionWatchResponse:
        watch = self.repository.get_decision_watch(watch_id)
        if not watch:
            raise LookupError("Decision Watch not found")
        if watch.status == "CANCELED":
            raise ValueError("A canceled Decision Watch cannot be reactivated")
        if watch.status == "PROPOSED":
            timestamp = _now_iso()
            watch.status = "ACTIVE"
            watch.approved_at = timestamp
            watch.next_run_at = timestamp
            watch.updated_at = timestamp
            self.repository.save_decision_watch(watch)
            self._event(
                watch.id,
                "WATCH_APPROVED",
                "Decision Watch approved",
                "The saved plan is active. Profile preferences and Fit Scores remain unchanged.",
                {"approved_at": timestamp, "run_now": run_now},
            )
        if run_now and watch.status == "ACTIVE":
            watch = await self.execute(watch.id)
        return self.response(watch)

    def cancel(self, watch_id: str) -> DecisionWatchResponse:
        watch = self.repository.get_decision_watch(watch_id)
        if not watch:
            raise LookupError("Decision Watch not found")
        if watch.status != "CANCELED":
            timestamp = _now_iso()
            watch.status = "CANCELED"
            watch.canceled_at = timestamp
            watch.next_run_at = None
            watch.updated_at = timestamp
            self.repository.save_decision_watch(watch)
            self._event(
                watch.id,
                "WATCH_CANCELED",
                "Decision Watch canceled",
                "No later scheduled execution can run for this watch.",
            )
        return self.response(watch)

    async def _execute_task(
        self,
        watch: DecisionWatch,
        task: DueDiligenceTask,
        source_cache: dict[str, tuple[int | None, str]],
    ) -> EvidenceRevision:
        listing = self.repository.get(task.listing_id)
        observed_at = _now_iso()
        before = EvidenceObservation(
            value=task.baseline_value,
            status=task.baseline_status,
            source_url=task.source_url,
            observed_at=task.baseline_observed_at,
        )
        outcome = "UNCHANGED"
        explanation = "The latest deterministic check matches the saved baseline."

        if not listing:
            after = EvidenceObservation(
                value="The catalog record is no longer available.",
                status="UNKNOWN",
                source_url=task.source_url,
                observed_at=observed_at,
            )
            outcome = "UNKNOWN"
            explanation = "Roamstead did not substitute another listing; this evidence is now unknown."
        elif task.tool in {"SOURCE_AVAILABILITY", "PRICE_COMPARISON"}:
            if listing.source_url not in source_cache:
                source_cache[listing.source_url] = await _fetch_source(listing.source_url)
            status_code, html = source_cache[listing.source_url]
            if task.tool == "SOURCE_AVAILABILITY":
                if status_code is not None and 200 <= status_code < 400:
                    value = f"Source page reachable (HTTP {status_code}); property availability remains unverified."
                    explanation = "The exact source page responded, but reachability is not proof that the property is still available."
                else:
                    value = "Source page could not be verified; property availability is unknown."
                    outcome = "UNKNOWN"
                    explanation = "The source could not be confirmed, so Roamstead lowered certainty instead of replacing evidence."
                after = EvidenceObservation(value=value, status="UNKNOWN", source_url=listing.source_url, observed_at=observed_at)
            else:
                current_vnd = _extract_source_price(html) if status_code and status_code < 400 else None
                if current_vnd is None:
                    after = EvidenceObservation(
                        value="The current advertised price could not be isolated reliably from the source page.",
                        status="UNKNOWN",
                        source_url=listing.source_url,
                        observed_at=observed_at,
                    )
                    outcome = "UNKNOWN"
                    explanation = "No reliable exact price was extracted; the saved price remains historical evidence only."
                else:
                    current_usd = round(current_vnd / max(1, int(os.getenv("VND_PER_USD", "26000"))))
                    value = f"VND {current_vnd:,} / USD {current_usd:,}"
                    outcome = "UNCHANGED" if current_vnd == listing.price_vnd else "CHANGED"
                    explanation = "The exact source-advertised VND price was compared with the saved catalog snapshot."
                    after = EvidenceObservation(value=value, status="CONFIRMED", source_url=listing.source_url, observed_at=observed_at)
        elif task.tool == "PHOTO_EVIDENCE":
            count = _photo_count(listing.id)
            value = f"{count} cached exact-listing photo{'s' if count != 1 else ''}"
            outcome = "UNCHANGED" if value == task.baseline_value else "CHANGED"
            after = EvidenceObservation(
                value=value,
                status="CONFIRMED" if count else "UNKNOWN",
                source_url=listing.source_url,
                observed_at=observed_at,
            )
            explanation = "Only photos already associated with this exact real listing were counted."
        elif task.tool == "CURRENCY_NORMALIZATION":
            rate = max(1, int(os.getenv("VND_PER_USD", "26000")))
            normalized = round(listing.price_vnd / rate)
            value = f"USD {normalized:,} from VND {listing.price_vnd:,} at {rate:,} VND/USD"
            outcome = "UNCHANGED" if normalized == listing.price_usd else "CHANGED"
            after = EvidenceObservation(value=value, status="INFERRED", source_url=listing.source_url, observed_at=observed_at)
            explanation = "USD is a deterministic display normalization; the source-reported VND price remains authoritative."
        else:
            school = listing.international_school_minutes_estimate
            food = listing.food_minutes_estimate
            value = f"School estimate: {school if school is not None else 'unknown'} min; food estimate: {food if food is not None else 'unknown'} min"
            status = "INFERRED" if school is not None and food is not None else "UNKNOWN"
            outcome = "UNCHANGED" if value == task.baseline_value else ("UNKNOWN" if status == "UNKNOWN" else "CHANGED")
            after = EvidenceObservation(value=value, status=status, source_url=listing.source_url, observed_at=observed_at)
            explanation = "These are catalog estimates, not a verified route; confirm the exact destination and traffic conditions before visiting."

        revision = EvidenceRevision(
            id=f"revision-{hashlib.sha256(f'{watch.id}:{watch.run_count}:{task.id}'.encode()).hexdigest()[:20]}",
            watch_id=watch.id,
            listing_id=task.listing_id,
            task_id=task.id,
            tool=task.tool,
            outcome=outcome,
            before=before,
            after=after,
            explanation=explanation,
        )
        return self.repository.save_evidence_revision(revision)

    async def execute(self, watch_id: str) -> DecisionWatch:
        watch = self.repository.get_decision_watch(watch_id)
        if not watch:
            raise LookupError("Decision Watch not found")
        if watch.status == "CANCELED":
            return watch
        if watch.status != "ACTIVE":
            raise ValueError("Decision Watch must be approved before execution")
        if watch.next_run_at and datetime.fromisoformat(watch.next_run_at) > _now():
            return watch

        watch.status = "RUNNING"
        watch.run_count += 1
        watch.updated_at = _now_iso()
        self.repository.save_decision_watch(watch)
        self._event(
            watch.id,
            "EXECUTION_STARTED",
            "Approved checks started",
            f"Running {len(watch.plan.tasks)} bounded checks across exactly three properties.",
            {"run_number": watch.run_count, "task_count": len(watch.plan.tasks)},
        )
        degraded = False
        source_cache: dict[str, tuple[int | None, str]] = {}
        for task in watch.plan.tasks:
            current = self.repository.get_decision_watch(watch.id)
            if current and current.status == "CANCELED":
                return current
            try:
                revision = await self._execute_task(watch, task, source_cache)
                self._event(
                    watch.id,
                    "TOOL_COMPLETED",
                    task.tool.replace("_", " ").title(),
                    revision.explanation,
                    {
                        "task_id": task.id,
                        "listing_id": task.listing_id,
                        "tool": task.tool,
                        "outcome": revision.outcome,
                        "before_status": revision.before.status,
                        "after_status": revision.after.status,
                    },
                )
                self._event(
                    watch.id,
                    "REVISION_CREATED",
                    "Evidence revision saved",
                    f"{task.tool.replace('_', ' ').title()}: {revision.outcome.lower()} for {task.listing_id}.",
                    {"revision_id": revision.id, "listing_id": task.listing_id, "outcome": revision.outcome},
                )
            except Exception as exc:
                degraded = True
                self._event(
                    watch.id,
                    "TOOL_DEGRADED",
                    f"{task.tool.replace('_', ' ').title()} unavailable",
                    "This check was not replaced with synthetic evidence and will be retried later.",
                    {"task_id": task.id, "listing_id": task.listing_id, "error_type": type(exc).__name__},
                )

        completed_at = _now()
        watch.status = "ACTIVE"
        watch.last_run_at = completed_at.isoformat()
        interval = max(1, int(os.getenv("ROAMSTEAD_WATCH_INTERVAL_DAYS", "7")))
        watch.next_run_at = (completed_at + timedelta(days=interval)).isoformat()
        watch.last_outcome = "DEGRADED" if degraded else "COMPLETED"
        watch.revision_count = len(self.repository.list_evidence_revisions(watch.id))
        watch.updated_at = completed_at.isoformat()
        self.repository.save_decision_watch(watch)
        self._event(
            watch.id,
            "WATCH_COMPLETED",
            "Decision Watch saved",
            "The evidence timeline was updated. No profile preference, hard filter, Fit Score, or listing was changed.",
            {
                "last_outcome": watch.last_outcome,
                "revision_count": watch.revision_count,
                "next_run_at": watch.next_run_at,
            },
        )
        return watch

    async def process_due(self, limit: int | None = None) -> list[DecisionWatch]:
        bounded_limit = min(
            max(1, limit or int(os.getenv("ROAMSTEAD_WATCH_MAX_PER_RUN", "5"))),
            5,
        )
        completed: list[DecisionWatch] = []
        for watch in self.repository.list_due_decision_watches(bounded_limit):
            completed.append(await self.execute(watch.id))
        return completed


decision_watch_service = DecisionWatchService()
