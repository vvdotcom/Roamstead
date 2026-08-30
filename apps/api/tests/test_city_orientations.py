from fastapi.testclient import TestClient

from app import city_orientations as catalog
from app.main import app


client = TestClient(app)


def test_city_orientation_catalog_is_bounded_and_marks_generated_media(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "get_document",
        lambda collection, slug: {
            "video_status": "READY",
            "narration_status": "READY",
            "generated_at": "2026-08-30T12:00:00+00:00",
        },
    )
    response = client.get("/api/v1/city-orientations")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 3
    assert {item["city"] for item in items} == {
        "Ho Chi Minh City",
        "Bangkok",
        "Kuala Lumpur",
    }
    assert all(item["video_model"] == "veo-3.1-lite-generate-preview" for item in items)
    assert all(item["narration_model"] == "gemini-3.1-flash-tts-preview" for item in items)
    assert all(item["video_url"].endswith("/video") for item in items)
    assert all(item["audio_url"].endswith("/audio") for item in items)
    assert all("not a property" in item["disclaimer"] for item in items)


def test_unknown_city_orientation_returns_404():
    assert client.get("/api/v1/city-orientations/not-a-city").status_code == 404


def test_asset_route_rejects_unknown_kind():
    assert client.get("/api/v1/city-orientations/bangkok/poster").status_code == 404
