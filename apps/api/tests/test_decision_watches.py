from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _profile_and_properties() -> tuple[str, list[dict]]:
    created = client.post("/api/v1/sessions", json={"housing_mode": "BUY"}).json()
    profile_id = created["session"]["profile_id"]
    search = client.post(
        "/api/v1/listings/search",
        json={"transaction_mode": "BUY", "profile_id": profile_id, "limit": 25},
    )
    assert search.status_code == 200
    return profile_id, search.json()["items"][:3]


def test_watch_requires_approval_is_idempotent_and_preserves_ranking(monkeypatch):
    monkeypatch.setattr("app.decision_watches.agent_enabled", lambda: False)

    async def reachable_source(_: str):
        return 200, "<html><body>real source page</body></html>"

    monkeypatch.setattr("app.decision_watches._fetch_source", reachable_source)
    profile_id, listings = _profile_and_properties()
    listing_ids = [item["id"] for item in listings]
    before_scores = {item["id"]: item["fit_score"] for item in listings}
    payload = {
        "profile_id": profile_id,
        "listing_ids": listing_ids,
        "idempotency_key": f"watch-test-{uuid4().hex}",
    }

    proposed = client.post("/api/v1/decision-watches", json=payload)
    assert proposed.status_code == 202
    body = proposed.json()
    assert body["watch"]["status"] == "PROPOSED"
    assert body["watch"]["approval_required"] is True
    assert body["watch"]["approved_at"] is None
    assert body["revisions"] == []
    assert len(body["watch"]["plan"]["tasks"]) <= 9
    assert {task["listing_id"] for task in body["watch"]["plan"]["tasks"]} == set(listing_ids)
    assert all(
        any(task["listing_id"] == listing_id and task["tool"] == "SOURCE_AVAILABILITY" for task in body["watch"]["plan"]["tasks"])
        for listing_id in listing_ids
    )

    repeated = client.post("/api/v1/decision-watches", json=payload).json()
    assert repeated["reused"] is True
    assert repeated["watch"]["id"] == body["watch"]["id"]

    approved = client.post(
        f"/api/v1/decision-watches/{body['watch']['id']}/approve",
        json={"run_now": True},
    )
    assert approved.status_code == 200
    completed = approved.json()
    assert completed["watch"]["status"] == "ACTIVE"
    assert completed["watch"]["approved_at"]
    assert completed["watch"]["last_outcome"] == "COMPLETED"
    assert completed["watch"]["next_run_at"]
    assert len(completed["revisions"]) == len(completed["watch"]["plan"]["tasks"])
    revision_ids = {item["id"] for item in completed["revisions"]}

    replay = client.post(
        f"/api/v1/decision-watches/{body['watch']['id']}/approve",
        json={"run_now": True},
    ).json()
    assert {item["id"] for item in replay["revisions"]} == revision_ids

    profile = client.get(f"/api/v1/profiles/{profile_id}").json()
    assert profile["version"] == 1
    refreshed = client.post(
        "/api/v1/listings/search",
        json={"transaction_mode": "BUY", "profile_id": profile_id, "limit": 25},
    ).json()["items"]
    refreshed_scores = {item["id"]: item["fit_score"] for item in refreshed if item["id"] in before_scores}
    assert refreshed_scores == before_scores


def test_cancel_prevents_execution(monkeypatch):
    monkeypatch.setattr("app.decision_watches.agent_enabled", lambda: False)
    profile_id, listings = _profile_and_properties()
    proposed = client.post(
        "/api/v1/decision-watches",
        json={
            "profile_id": profile_id,
            "listing_ids": [item["id"] for item in listings],
            "idempotency_key": f"cancel-test-{uuid4().hex}",
        },
    ).json()
    watch_id = proposed["watch"]["id"]
    canceled = client.post(f"/api/v1/decision-watches/{watch_id}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["watch"]["status"] == "CANCELED"
    assert canceled.json()["watch"]["next_run_at"] is None
    rejected = client.post(
        f"/api/v1/decision-watches/{watch_id}/approve", json={"run_now": True}
    )
    assert rejected.status_code == 409
    assert client.get(f"/api/v1/decision-watches/{watch_id}").json()["revisions"] == []


def test_watch_rejects_any_selection_other_than_three_unique_properties(monkeypatch):
    monkeypatch.setattr("app.decision_watches.agent_enabled", lambda: False)
    profile_id, listings = _profile_and_properties()
    response = client.post(
        "/api/v1/decision-watches",
        json={"profile_id": profile_id, "listing_ids": [listings[0]["id"]] * 3},
    )
    assert response.status_code == 422


def test_live_planner_selection_is_bounded_and_persisted_as_adk(monkeypatch):
    monkeypatch.setattr("app.decision_watches.agent_enabled", lambda: True)

    async def selected_plan(profile, listings, candidates):
        source_ids = [task.id for task in candidates if task.tool == "SOURCE_AVAILABILITY"]
        property_specific = [
            task.id
            for task in candidates
            if task.tool in {"PHOTO_EVIDENCE", "PROXIMITY_VERIFICATION", "PRICE_COMPARISON"}
        ][:4]
        return source_ids + property_specific, "Selected source and gap-specific checks for the three homes."

    monkeypatch.setattr("app.decision_watches._model_selection", selected_plan)
    profile_id, listings = _profile_and_properties()
    response = client.post(
        "/api/v1/decision-watches",
        json={
            "profile_id": profile_id,
            "listing_ids": [item["id"] for item in listings],
            "idempotency_key": f"live-plan-test-{uuid4().hex}",
        },
    )
    assert response.status_code == 202
    plan = response.json()["watch"]["plan"]
    assert plan["provider"] == "GOOGLE_ADK"
    assert plan["degraded"] is False
    assert 3 <= len(plan["tasks"]) <= 9
    assert all(
        any(task["listing_id"] == listing["id"] and task["tool"] == "SOURCE_AVAILABILITY" for task in plan["tasks"])
        for listing in listings
    )
