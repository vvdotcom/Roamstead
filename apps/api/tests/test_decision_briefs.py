import asyncio
from fastapi.testclient import TestClient
from uuid import uuid4

from app.decision_briefs import decision_brief_service
from app.main import app
from app.models import (
    MemoryConsistencyAudit,
    MemoryContextPacket,
    PropertyVisualAudit,
    VisualEvidenceAudit,
    VisualImageAssessment,
)


client = TestClient(app)


def _profile_and_listings(mode: str = "BUY") -> tuple[str, list[dict]]:
    created = client.post("/api/v1/sessions", json={"housing_mode": mode}).json()
    profile_id = created["session"]["profile_id"]
    response = client.post(
        "/api/v1/listings/search",
        json={"transaction_mode": mode, "profile_id": profile_id, "limit": 100},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 3
    return profile_id, items


def test_listing_feedback_requires_approval_then_reorders_real_properties(monkeypatch):
    async def related_embedding(text: str, task_type: str):
        return [1.0, *([0.0] * 767)]

    monkeypatch.setattr("app.semantic_memory.embed_text", related_embedding)
    profile_id, items = _profile_and_listings()
    original_ids = [item["id"] for item in items]

    first = client.post(
        f"/api/v1/profiles/{profile_id}/feedback",
        json={"target_id": original_ids[0], "action": "REJECT", "reason": "TOO_EXPENSIVE", "note": "The monthly cost leaves too little room for school fees."},
    ).json()
    assert first["proposal"] is None
    second = client.post(
        f"/api/v1/profiles/{profile_id}/feedback",
        json={"target_id": original_ids[1], "action": "REJECT", "reason": "TOO_EXPENSIVE", "note": "This price would make our overall family budget uncomfortable."},
    ).json()
    proposal = second["proposal"]
    assert proposal["key"] == "budget"
    assert second["memory_context"]["selected_count"] >= 1
    assert second["profile"]["version"] == 1

    applied = client.post(
        f"/api/v1/profiles/{profile_id}/preference-proposals/{proposal['id']}/decision",
        json={"decision": "ACCEPT"},
    )
    assert applied.status_code == 200
    assert applied.json()["profile"]["version"] == 2

    refreshed = client.post(
        "/api/v1/listings/search",
        json={"transaction_mode": "BUY", "profile_id": profile_id, "limit": 100},
    ).json()["items"]
    assert all(item["demo"] is False for item in refreshed)
    assert all(item["fit_score"] > 0 for item in refreshed)


def test_decision_brief_is_evidence_labeled_persisted_and_idempotent(monkeypatch):
    monkeypatch.setattr("app.decision_briefs.agent_enabled", lambda: False)
    profile_id, items = _profile_and_listings("RENT")
    listing_ids = [item["id"] for item in items[:3]]
    payload = {"profile_id": profile_id, "listing_ids": listing_ids, "idempotency_key": f"golden-test-{uuid4().hex}"}

    created = client.post("/api/v1/decision-briefs", json=payload)
    assert created.status_code == 202
    result = created.json()
    run_id = result["run"]["id"]
    assert result["reused"] is False
    assert result["run"]["status"] == "QUEUED"
    assert result["brief"] is None

    replay = client.get(f"/api/v1/decision-briefs/{run_id}/events")
    assert replay.status_code == 200
    assert "event: tool_result" in replay.text
    assert '"event_type": "TOOL_RESULT"' in replay.text
    assert '"event_type": "RUN_COMPLETED"' in replay.text
    assert "event: stream_end" in replay.text

    persisted = client.get(f"/api/v1/decision-briefs/{run_id}")
    assert persisted.status_code == 200
    brief = persisted.json()
    assert brief["status"] == "COMPLETED"
    assert len(brief["properties"]) == 3
    assert {claim["status"] for prop in brief["properties"] for claim in prop["evidence"]} >= {"CONFIRMED", "UNKNOWN"}
    assert all(prop["source_url"].startswith("https://batdongsan.com.vn/") for prop in brief["properties"])
    assert all(prop["image_urls"] for prop in brief["properties"])

    assert brief["run_id"] == run_id

    repeated = client.post("/api/v1/decision-briefs", json=payload).json()
    assert repeated["reused"] is True
    assert repeated["run"]["id"] == run_id
    assert repeated["brief"]["status"] == "COMPLETED"


def test_live_specialists_and_multimodal_gemma_audit_are_persisted(monkeypatch):
    monkeypatch.setattr("app.decision_briefs.agent_enabled", lambda: True)
    monkeypatch.setattr("app.decision_briefs.build_listing_analyst", lambda: object())
    monkeypatch.setattr("app.decision_briefs.build_evidence_verifier", lambda: object())
    monkeypatch.setattr("app.decision_briefs.build_brief_composer", lambda: object())

    async def fake_adk(run, *, actor, stage, agent, prompt, attempt):
        decision_brief_service._event(
            run,
            decision_brief_service._next_sequence(run.id),
            "SPECIALIST_STARTED",
            actor,
            f"{actor} started",
            "A public specialist boundary was persisted before work completed.",
            status="RUNNING",
            phase=stage,
            model=run.model,
            provider="GOOGLE_ADK",
        )
        await asyncio.sleep(0.002)
        output = "VERIFIED" if actor == "EvidenceVerifier" else f"{actor} completed from the saved evidence packet."
        decision_brief_service._event(
            run,
            decision_brief_service._next_sequence(run.id),
            "SPECIALIST_COMPLETED",
            actor,
            f"{actor} completed",
            output,
            phase=stage,
            model=run.model,
            provider="GOOGLE_ADK",
            duration_ms=2,
        )
        decision_brief_service._checkpoint(run, stage, output, model=run.model)
        return output

    async def fake_gemma(run, *, stage, evidence_packet, analysis, images, attempt, parallel_group=None):
        decision_brief_service._event(
            run,
            decision_brief_service._next_sequence(run.id),
            "SPECIALIST_STARTED",
            "VisualEvidenceCritic",
            "Gemma visual audit started",
            f"Auditing {len(images)} locally cached exact-listing photos.",
            status="RUNNING",
            phase=stage,
            model="gemma-4-26b-a4b-it",
            provider="GEMINI_API",
            parallel_group=parallel_group,
        )
        await asyncio.sleep(0.002)
        grouped = []
        for packet in evidence_packet:
            listing_id = packet["listing_id"]
            listing_images = [item for item in images if item.listing_id == listing_id]
            grouped.append(
                PropertyVisualAudit(
                    listing_id=listing_id,
                    verdict="SUPPORTED",
                    images=[
                        VisualImageAssessment(
                            image_index=item.image_index,
                            image_url=item.image_url,
                            classification="INTERIOR",
                            observations=["A window and finished floor are directly visible."],
                            confidence="HIGH",
                        )
                        for item in listing_images
                    ],
                    suggested_questions=["Request a current live video tour of the exact property."],
                )
            )
        audit = VisualEvidenceAudit(
            verdict="SUPPORTED",
            summary="The real cached photos support only the listed observable features.",
            properties=grouped,
            model="gemma-4-26b-a4b-it",
            provider="GEMINI_API",
            analyzed_photo_count=len(images),
        )
        decision_brief_service._event(
            run,
            decision_brief_service._next_sequence(run.id),
            "SPECIALIST_COMPLETED",
            "VisualEvidenceCritic",
            "Gemma visual audit completed",
            audit.summary,
            audit.model_dump(mode="json"),
            phase=stage,
            model=audit.model,
            provider=audit.provider,
            duration_ms=2,
            parallel_group=parallel_group,
        )
        decision_brief_service._checkpoint(run, stage, audit, model=audit.model)
        return audit

    async def fake_memory(run, profile):
        packet = MemoryContextPacket(
            query="fixture housing preferences",
            considered_count=2,
            selected_count=0,
            excluded_count=2,
            status="READY",
        )
        decision_brief_service._event(
            run,
            decision_brief_service._next_sequence(run.id),
            "SEMANTIC_MEMORY_STARTED",
            "SemanticMemoryTool",
            "Semantic memory started",
            "A fixture query started.",
            status="RUNNING",
            phase="SEMANTIC_MEMORY",
            model="gemini-embedding-001",
            provider="GEMINI_API_FIRESTORE",
        )
        await asyncio.sleep(0.002)
        decision_brief_service._event(
            run,
            decision_brief_service._next_sequence(run.id),
            "SEMANTIC_MEMORY_COMPLETED",
            "SemanticMemoryTool",
            "Semantic memory completed",
            "A fixture memory packet was persisted.",
            packet.model_dump(mode="json"),
            phase="SEMANTIC_MEMORY",
            model="gemini-embedding-001",
            provider="GEMINI_API_FIRESTORE",
            duration_ms=2,
        )
        decision_brief_service._checkpoint(run, "SEMANTIC_MEMORY", packet, model="gemini-embedding-001")
        return packet

    async def fake_memory_critic(
        run,
        *,
        stage,
        profile,
        memory_context,
        evidence_packet,
        analysis,
        visual_audit,
        attempt,
        parallel_group=None,
    ):
        audit = MemoryConsistencyAudit(
            verdict="CONSISTENT",
            summary="The public comparison stays within the approved profile and fixture memory packet.",
            model="gemma-4-31b-it",
            duration_ms=2,
        )
        decision_brief_service._event(
            run,
            decision_brief_service._next_sequence(run.id),
            "SPECIALIST_STARTED",
            "MemoryConsistencyCritic",
            "Memory critic started",
            "Gemma 31B started a fixture audit.",
            status="RUNNING",
            phase=stage,
            model=audit.model,
            provider=audit.provider,
            parallel_group=parallel_group,
        )
        await asyncio.sleep(0.002)
        decision_brief_service._event(
            run,
            decision_brief_service._next_sequence(run.id),
            "SPECIALIST_COMPLETED",
            "MemoryConsistencyCritic",
            "Memory critic completed",
            audit.summary,
            audit.model_dump(mode="json"),
            phase=stage,
            model=audit.model,
            provider=audit.provider,
            duration_ms=2,
            parallel_group=parallel_group,
        )
        decision_brief_service._checkpoint(run, stage, audit, model=audit.model)
        return audit

    monkeypatch.setattr(decision_brief_service, "_run_adk_specialist", fake_adk)
    monkeypatch.setattr(decision_brief_service, "_run_visual_critic", fake_gemma)
    monkeypatch.setattr(decision_brief_service, "_run_semantic_memory", fake_memory)
    monkeypatch.setattr(decision_brief_service, "_run_memory_critic", fake_memory_critic)

    profile_id, items = _profile_and_listings("RENT")
    response = client.post(
        "/api/v1/decision-briefs",
        json={
            "profile_id": profile_id,
            "listing_ids": [item["id"] for item in items[:3]],
            "idempotency_key": f"live-gemma-{uuid4().hex}",
        },
    )
    assert response.status_code == 202
    run_id = response.json()["run"]["id"]
    stream = client.get(f"/api/v1/decision-briefs/{run_id}/events")
    assert stream.status_code == 200
    assert stream.text.index("event: specialist_started") < stream.text.index("event: specialist_completed")
    assert "VisualEvidenceCritic" in stream.text
    assert "gemma-4-26b-a4b-it" in stream.text

    brief = client.get(f"/api/v1/decision-briefs/{run_id}").json()
    assert brief["degraded"] is False
    assert brief["visual_audit"]["succeeded"] is True
    assert brief["visual_audit"]["analyzed_photo_count"] == 3
    assert "gemma-4-26b-a4b-it" in brief["models_used"]
    assert "gemma-4-31b-it" in brief["models_used"]
    assert "gemini-embedding-001" in brief["models_used"]
    assert brief["memory_context"]["status"] == "READY"
    assert brief["memory_audit"]["succeeded"] is True
    assert all(item["visual_audit"]["images"] for item in brief["properties"])

    events = decision_brief_service.repository.list_agent_events(run_id)
    critic_starts = [
        event
        for event in events
        if event.event_type == "SPECIALIST_STARTED"
        and event.actor in {"VisualEvidenceCritic", "MemoryConsistencyCritic"}
        and event.parallel_group == "CRITICS_1"
    ]
    join = next(event for event in events if event.actor == "CriticJoin")
    assert {event.actor for event in critic_starts} == {"VisualEvidenceCritic", "MemoryConsistencyCritic"}
    assert all(event.sequence < join.sequence for event in critic_starts)
    assert join.node_kind == "JOIN"
    assert join.parallel_group == "CRITICS_1"
    assert next(event for event in events if event.actor == "CorrectionRouter").node_kind == "ROUTER"
    first_completed = next(event.sequence for event in events if event.event_type == "SPECIALIST_COMPLETED")
    replay = client.get(f"/api/v1/decision-briefs/{run_id}/events?after={first_completed}")
    assert f"id: {first_completed}\n" not in replay.text
    assert "event: stream_end" in replay.text
