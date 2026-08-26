from app.listings.live_search import (
    _batdongsan_upload_time,
    _gallery_urls_from_payload,
    _is_google_grounding_redirect,
)


def test_grounding_redirect_accepts_base64_padding() -> None:
    url = (
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"
        "AUZIYQ" + "A" * 80 + "="
    )
    assert _is_google_grounding_redirect(url)


def test_gallery_parser_keeps_only_exact_property_photos() -> None:
    good = "https://images.example.com/listing/living-room.jpg"
    payload = {
        "images": [
            {
                "source_url": "https://batdongsan.com.vn/exact-pr123",
                "image_url": good,
                "kind": "living_room",
                "is_property_photo": True,
                "is_exact_listing": True,
            },
            {
                "source_url": "https://batdongsan.com.vn/exact-pr123",
                "image_url": "https://images.example.com/listing/deed.jpg",
                "kind": "title_deed",
                "is_property_photo": True,
                "is_exact_listing": True,
            },
            {
                "source_url": "https://batdongsan.com.vn/other-pr456",
                "image_url": "https://images.example.com/other/bedroom.jpg",
                "kind": "bedroom",
                "is_property_photo": True,
                "is_exact_listing": False,
            },
        ]
    }
    assert _gallery_urls_from_payload(payload, "https://batdongsan.com.vn/exact-pr123") == [good]


def test_batdongsan_upload_time_requires_official_timestamped_asset() -> None:
    official = "https://file4.batdongsan.com.vn/crop/656x368/2026/08/15/20260815110859-f6cb_wm.jpg"
    other_portal = "https://images.example.com/2026/08/15/20260815110859-f6cb_wm.jpg"
    parsed = _batdongsan_upload_time(official)
    assert parsed is not None
    assert parsed.isoformat() == "2026-08-15T11:08:59+00:00"
    assert _batdongsan_upload_time(other_portal) is None
