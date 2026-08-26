import asyncio

from fastapi.testclient import TestClient

from app.listings.repository import ListingRepository
from app.listings.catalog import listing_catalog
from app.main import app
from app.semantic_memory import make_memory, persist_memory, retrieve_memory


def _vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * 766)]


def test_fixture_vectors_are_profile_isolated_ordered_and_idempotent(tmp_path, monkeypatch):
    repository = ListingRepository(tmp_path / "memory.db")

    async def fake_embed(text: str, task_type: str):
        if "unrelated" in text:
            return _vector(0.0, 1.0)
        return _vector(1.0, 0.0)

    monkeypatch.setattr("app.semantic_memory.embed_text", fake_embed)
    first = make_memory(
        profile_id="profile-a",
        source_event_id="feedback-1",
        kind="FEEDBACK",
        preference_key="quiet",
        source_text="The traffic noise made this home feel too urban.",
    )
    duplicate = first.model_copy()
    unrelated = make_memory(
        profile_id="profile-a",
        source_event_id="feedback-2",
        kind="FEEDBACK",
        preference_key="quiet",
        source_text="unrelated preference signal",
    )
    other_profile = make_memory(
        profile_id="profile-b",
        source_event_id="feedback-3",
        kind="FEEDBACK",
        preference_key="quiet",
        source_text="The street activity made this feel too busy.",
    )
    cross_city = make_memory(
        profile_id="profile-a",
        source_event_id="feedback-4",
        kind="FEEDBACK",
        preference_key="quiet",
        source_text="A calmer street matters in my housing decision.",
        city="Da Nang",
    )
    for item in (first, duplicate, unrelated, other_profile, cross_city):
        asyncio.run(persist_memory(repository, item))

    packet = asyncio.run(
        retrieve_memory(repository, "profile-a", "I want somewhere calmer and less hectic", preference_key="quiet")
    )
    assert packet.status == "READY"
    assert {item.memory_id for item in packet.matches} == {first.id, cross_city.id}
    assert all(item.cosine_distance == 0 for item in packet.matches)
    assert any(item.city == "Da Nang" for item in packet.matches)
    assert len(repository.list_semantic_memory("profile-a")) == 3
    assert packet.context_characters <= 6000


def test_public_semantic_memory_never_exposes_vectors(monkeypatch):
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={"housing_mode": "BUY"}).json()
    profile_id = created["session"]["profile_id"]
    item = make_memory(
        profile_id=profile_id,
        source_event_id=f"public-{profile_id}",
        kind="FEEDBACK",
        preference_key="quiet",
        source_text="I prefer a calmer street.",
    )
    item.embedding = _vector(1.0)
    item.embedding_status = "READY"
    from app.listings.catalog import listing_catalog

    listing_catalog.repository.save_semantic_memory(item)
    response = client.get(f"/api/v1/profiles/{profile_id}/semantic-memory")
    assert response.status_code == 200
    assert response.json()
    assert all("embedding" not in record for record in response.json())


def test_embedding_failure_persists_pending_and_retries_on_retrieval(tmp_path, monkeypatch):
    repository = ListingRepository(tmp_path / "retry.db")

    async def timeout_embed(text: str, task_type: str):
        raise TimeoutError("fixture timeout")

    monkeypatch.setattr("app.semantic_memory.embed_text", timeout_embed)
    item = make_memory(
        profile_id="profile-retry",
        source_event_id="feedback-timeout",
        kind="FEEDBACK",
        preference_key="quiet",
        source_text="Traffic noise is too intense.",
    )
    pending = asyncio.run(persist_memory(repository, item))
    assert pending.embedding_status == "PENDING_EMBEDDING"
    assert pending.embedding == []

    async def recovered_embed(text: str, task_type: str):
        return _vector(1.0)

    monkeypatch.setattr("app.semantic_memory.embed_text", recovered_embed)
    packet = asyncio.run(retrieve_memory(repository, "profile-retry", "I want less traffic noise"))
    assert packet.status == "READY"
    assert repository.get_semantic_memory(item.id).embedding_status == "READY"


def test_semantic_memory_does_not_change_filters_or_fit_scores(monkeypatch):
    async def related_embedding(text: str, task_type: str):
        return _vector(1.0)

    monkeypatch.setattr("app.semantic_memory.embed_text", related_embedding)
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={"housing_mode": "BUY"}).json()
    profile_id = created["session"]["profile_id"]
    before = client.post(
        "/api/v1/listings/search",
        json={"transaction_mode": "BUY", "profile_id": profile_id, "limit": 100},
    ).json()["items"]
    item = make_memory(
        profile_id=profile_id,
        source_event_id=f"fit-invariance-{profile_id}",
        kind="FEEDBACK",
        preference_key="quiet",
        source_text="I prefer a calmer street.",
    )
    asyncio.run(persist_memory(listing_catalog.repository, item))
    after = client.post(
        "/api/v1/listings/search",
        json={"transaction_mode": "BUY", "profile_id": profile_id, "limit": 100},
    ).json()["items"]
    assert [(item["id"], item["fit_score"]) for item in before] == [
        (item["id"], item["fit_score"]) for item in after
    ]
