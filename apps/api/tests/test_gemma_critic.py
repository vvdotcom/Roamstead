from pathlib import Path

import pytest
from PIL import Image

from app import gemma_critic


def _image(tmp_path: Path, listing_id: str = "real-1") -> gemma_critic.VisualImageInput:
    path = tmp_path / f"{listing_id}.jpg"
    Image.new("RGB", (48, 32), color=(44, 91, 132)).save(path, format="JPEG")
    return gemma_critic.VisualImageInput(
        listing_id=listing_id,
        image_index=0,
        image_url=f"/api/v1/listings/{listing_id}/images/0",
        path=path,
    )


def test_visual_audit_normalizes_typed_property_and_image_output(tmp_path):
    image = _image(tmp_path)
    result = gemma_critic._normalize(
        '{"verdict":"SUPPORTED","summary":"The attached image shows an interior.",'
        '"challenged_claims":[],"properties":[{"listing_id":"real-1","verdict":"SUPPORTED",'
        '"images":[{"image_index":0,"classification":"INTERIOR","observations":["A window and tiled floor are visible."],'
        '"warnings":[],"confidence":"HIGH"}],"unsupported_claims":[],"missing_evidence":[],"suggested_questions":[]}]}',
        "GEMINI_API",
        [image],
    )
    assert result.verdict == "SUPPORTED"
    assert result.model.startswith("gemma-4")
    assert result.analyzed_photo_count == 1
    assert result.properties[0].images[0].image_url == image.image_url
    assert result.properties[0].images[0].classification == "INTERIOR"


def test_visual_audit_fills_missing_model_result_without_fabricating(tmp_path):
    image = _image(tmp_path)
    result = gemma_critic._normalize(
        '{"verdict":"SUPPORTED","summary":"No property result returned.","properties":[],"challenged_claims":[]}',
        "GEMINI_API",
        [image],
    )
    assert result.properties[0].verdict == "INSUFFICIENT"
    assert result.properties[0].images[0].classification == "UNKNOWN"
    assert "did not return" in result.properties[0].missing_evidence[0]


@pytest.mark.asyncio
async def test_gemma_critic_sends_real_local_image_to_configured_model(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_GEMMA_CRITIC", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMMA_CRITIC_URL", raising=False)
    image = _image(tmp_path)

    async def fake_call(prompt: str, images: list[gemma_critic.VisualImageInput]):
        assert "VisualEvidenceCritic" in prompt
        assert images == [image]
        return gemma_critic._normalize(
            '{"verdict":"SUPPORTED","summary":"Observable image evidence only.","properties":[],"challenged_claims":[]}',
            "GEMINI_API",
            images,
        )

    monkeypatch.setattr(gemma_critic, "_audit_with_gemini_api", fake_call)
    result = await gemma_critic.audit_visual_evidence([{"listing_id": "real-1"}], {"ListingAnalyst": "public result"}, [image])
    assert result is not None
    assert result.provider == "GEMINI_API"
    assert result.analyzed_photo_count == 1


@pytest.mark.asyncio
async def test_gemma_critic_rejects_missing_local_images(monkeypatch):
    monkeypatch.setenv("ENABLE_GEMMA_CRITIC", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with pytest.raises(ValueError, match="No locally cached real listing photos"):
        await gemma_critic.audit_visual_evidence([], {}, [])


def test_visual_audit_rejects_malformed_json(tmp_path):
    with pytest.raises(ValueError, match="no JSON object"):
        gemma_critic._normalize("not-json", "GEMINI_API", [_image(tmp_path)])
