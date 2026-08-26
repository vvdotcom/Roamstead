from fastapi.testclient import TestClient

from app.main import app
from app.agent import build_decision_workflow
from app.clarifications import _agent_result_texts
from app.store import store


client = TestClient(app)


def test_golden_demo_requires_confirmation_and_reranks():
    created = client.post("/api/v1/sessions").json()
    session_id = created["session"]["id"]
    profile_id = created["session"]["profile_id"]

    ready = client.post(f"/api/v1/sessions/{session_id}/message", json={"message": "Move to HCMC"})
    assert ready.json()["stage"] == "DISCOVERY"
    assert ready.json()["question"] is None
    initial_leader = ready.json()["recommendations"][0]["name"]

    one = client.post(f"/api/v1/profiles/{profile_id}/feedback", json={"target_id": "thu-thiem", "action": "REJECT", "reason": "TOO_URBAN"}).json()
    assert one["proposal"] is None
    two = client.post(f"/api/v1/profiles/{profile_id}/feedback", json={"target_id": "binh-thanh", "action": "REJECT", "reason": "TOO_URBAN"}).json()
    proposal = two["proposal"]
    assert proposal["status"] == "AWAITING_CONFIRMATION"

    # Merely detecting a pattern cannot change the ranking.
    unchanged = client.get("/api/v1/recommendations/neighborhoods", params={"profile_id": profile_id}).json()
    assert unchanged["items"][0]["name"] == initial_leader

    applied = client.post(
        f"/api/v1/profiles/{profile_id}/preference-proposals/{proposal['id']}/decision",
        json={"decision": "ACCEPT"},
    ).json()
    assert next(item for item in applied["profile"]["preferences"] if item["key"] == "quiet")["weight"] == 0.85
    assert any(item["previous_score"] != item["new_score"] for item in applied["deltas"])


def test_evidence_is_non_definitive_and_sourced():
    evidence = client.get("/api/v1/rule-evidence").json()
    assert evidence["status"] == "REQUIRES_VERIFICATION"
    assert evidence["source_url"].startswith("https://")
    assert evidence["last_checked"]


def test_rent_mode_builds_a_rental_profile():
    created = client.post("/api/v1/sessions", json={"housing_mode": "RENT"}).json()
    session = created["session"]
    assert session["housing_mode"] == "RENT"
    profile = client.get(f"/api/v1/profiles/{session['profile_id']}").json()
    assert any(item["key"] == "rent_budget" and item["value"] == 1500 for item in profile["hard_constraints"])
    assert any(item["key"] == "rent" and item["label"] == "Rent first" for item in profile["preferences"])
    assert any(item["key"] == "max_international_school_minutes" for item in profile["hard_constraints"])
    assert any(item["key"] == "max_food_minutes" for item in profile["hard_constraints"])
    assert any(item["key"] == "international_school" for item in profile["preferences"])
    assert any(item["key"] == "food_access" for item in profile["preferences"])


def test_session_survives_process_cache_loss():
    created = client.post("/api/v1/sessions", json={"housing_mode": "BUY"}).json()
    session_id = created["session"]["id"]
    profile_id = created["session"]["profile_id"]

    # Cloud Run may route the next request to another instance. Both the
    # collaboration session and its profile must hydrate from durable storage.
    store.sessions.pop(session_id)
    store.profiles.pop(profile_id)
    store.rankings.pop(profile_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/message",
        json={"message": "Continue my HCMC search"},
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "DISCOVERY"
    assert store.sessions[session_id].stage == "DISCOVERY"


def test_adaptive_clarification_uses_counterfactual_data_and_requires_approval(monkeypatch):
    monkeypatch.setattr("app.clarifications.agent_enabled", lambda: False)
    created = client.post("/api/v1/sessions", json={"housing_mode": "BUY"}).json()
    profile_id = created["session"]["profile_id"]
    original = client.get(f"/api/v1/profiles/{profile_id}").json()

    planned = client.post(f"/api/v1/profiles/{profile_id}/clarification")
    assert planned.status_code == 200
    question = planned.json()["question"]
    assert question["eligible_listing_count"] > 0
    assert len(question["options"]) == 3
    assert "ocean" not in question["question"].casefold()
    assert planned.json()["events"][1]["actor"] == "CounterfactualRankingTool"

    selected = next(option for option in question["options"] if option["preference_key"])
    answered = client.post(
        f"/api/v1/profiles/{profile_id}/clarifications/{question['id']}/answer",
        json={"option_id": selected["id"]},
    )
    assert answered.status_code == 200
    proposal = answered.json()["proposal"]
    assert proposal["status"] == "AWAITING_CONFIRMATION"
    assert proposal["source_clarification_id"] == question["id"]
    assert answered.json()["profile"]["version"] == original["version"]
    original_weight = next(item["weight"] for item in original["preferences"] if item["key"] == proposal["key"])
    answered_weight = next(item["weight"] for item in answered.json()["profile"]["preferences"] if item["key"] == proposal["key"])
    assert answered_weight == original_weight

    accepted = client.post(
        f"/api/v1/profiles/{profile_id}/preference-proposals/{proposal['id']}/decision",
        json={"decision": "ACCEPT"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["profile"]["version"] == original["version"] + 1
    assert next(item["weight"] for item in accepted.json()["profile"]["preferences"] if item["key"] == proposal["key"]) == proposal["proposed_weight"]


def test_adk_decision_workflow_has_explicit_specialist_order():
    workflow = build_decision_workflow()
    assert workflow.name == "PartnerCoordinator"
    assert [node.name for node in workflow.graph.nodes] == [
        "__START__",
        "ListingAnalyst",
        "EvidenceVerifier",
        "BriefComposer",
    ]


def test_clarification_reads_adk_task_result():
    class Event:
        content = None
        output = {"result": '{"question":"Adaptive?","why_asked":"Rank impact."}'}

    assert _agent_result_texts([Event()]) == ['{"question":"Adaptive?","why_asked":"Rank impact."}']


def test_user_can_edit_profile_and_reload_it_from_sqlite():
    created = client.post("/api/v1/sessions", json={"housing_mode": "BUY"}).json()
    profile_id = created["session"]["profile_id"]
    payload = {
        "budget_usd": 240000,
        "min_beds": 3,
        "min_baths": 2,
        "property_types": ["House"],
        "priorities": {
            "budget": 0.7,
            "space": 0.95,
            "healthcare": 0.8,
            "remote_work": 1,
            "waterfront": 0.35,
            "quiet": 0.75,
        },
    }

    updated = client.put(f"/api/v1/profiles/{profile_id}", json=payload)
    assert updated.status_code == 200
    assert updated.json()["profile"]["version"] == 2
    assert any(item["key"] == "min_beds" and item["value"] == 3 for item in updated.json()["profile"]["hard_constraints"])
    assert not any(item["key"] == "min_area_sqm" for item in updated.json()["profile"]["hard_constraints"])
    assert any(item["key"] == "property_types" and item["value"] == "House" for item in updated.json()["profile"]["hard_constraints"])

    # Simulate an API restart/cache miss: the profile must reload from SQLite.
    store.profiles.pop(profile_id)
    store.rankings.pop(profile_id)
    restored = client.get(f"/api/v1/profiles/{profile_id}")
    assert restored.status_code == 200
    assert restored.json()["version"] == 2
    assert any(item["key"] == "quiet" and item["weight"] == 0.75 for item in restored.json()["preferences"])


def test_listing_catalog_never_uses_synthetic_fallback(monkeypatch):
    created = client.post("/api/v1/sessions", json={"housing_mode": "RENT"}).json()
    profile_id = created["session"]["profile_id"]
    for name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_CLOUD_PROJECT",
        "GCP_PROJECT_ID",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_GENAI_USE_VERTEXAI",
    ):
        monkeypatch.delenv(name, raising=False)
    status = client.get("/api/v1/listings/status").json()
    assert status["configured"] is False
    assert status["synthetic_fallback"] is False
    response = client.post(
        "/api/v1/listings/search",
        json={"transaction_mode": "RENT", "profile_id": profile_id, "limit": 100},
    )
    if response.status_code == 200:
        # A saved real-data catalog remains usable when Gemini is offline.
        items = response.json()["items"]
        assert items
        assert all(item["demo"] is False for item in items)
        assert all(item["source_domain"] == "batdongsan.com.vn" for item in items)
        assert all(0 < item["fit_score"] <= 100 for item in items)
        assert all(item["fit_breakdown"] for item in items)
        assert all(item["fit_reasons"] for item in items)
        assert all("international_school" in item["fit_breakdown"] for item in items)
        assert all("food_access" in item["fit_breakdown"] for item in items)
        assert all(item["international_school_minutes_estimate"] is not None for item in items)
        assert all(item["food_minutes_estimate"] is not None for item in items)
    else:
        assert response.status_code == 503
        assert "No synthetic listings are used" in response.json()["detail"]
