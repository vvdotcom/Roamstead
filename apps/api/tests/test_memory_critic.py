import asyncio
import json

from app.memory_critic import audit_memory_consistency
from app.models import MemoryContextMatch, MemoryContextPacket


class _Response:
    text = json.dumps(
        {
            "verdict": "CHALLENGE",
            "summary": "The analysis assumes the user accepted a preference that they rejected.",
            "relevant_memory_ids": ["memory-valid", "memory-invented"],
            "conflicting_preferences": ["Quiet preference was proposed but rejected."],
            "superseded_preferences": [],
            "unsupported_user_assumptions": ["The user requires a silent neighborhood."],
            "omitted_tradeoffs": [],
            "suggested_questions": ["Should quiet remain flexible for this shortlist?"],
        }
    )


class _Models:
    def generate_content(self, **kwargs):
        assert kwargs["model"] == "gemma-4-31b-it"
        return _Response()


class _Client:
    def __init__(self, **kwargs):
        self.models = _Models()


def test_memory_critic_returns_typed_bounded_public_audit(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-key")
    monkeypatch.setattr("app.memory_critic.genai.Client", _Client)
    packet = MemoryContextPacket(
        query="quiet preference",
        matches=[
            MemoryContextMatch(
                memory_id="memory-valid",
                kind="PROPOSAL_DECISION",
                preference_key="quiet",
                text="Rejected a stronger quiet preference.",
                decision_status="REJECTED",
                cosine_distance=0.1,
                created_at="2026-08-23T00:00:00+00:00",
            )
        ],
        considered_count=1,
        selected_count=1,
        status="READY",
    )
    audit = asyncio.run(
        audit_memory_consistency(
            profile={"profile_id": "profile-a", "preferences": []},
            memory_context=packet,
            evidence_packet=[],
            listing_analysis="The user requires a silent neighborhood.",
            visual_audit=None,
        )
    )
    assert audit is not None
    assert audit.verdict == "CHALLENGE"
    assert audit.relevant_memory_ids == ["memory-valid"]
    assert audit.model == "gemma-4-31b-it"
