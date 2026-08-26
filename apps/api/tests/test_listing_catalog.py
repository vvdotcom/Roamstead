from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.listings.catalog import ListingCatalog
from app.listings.live_search import (
    GeminiLiveListingSearch,
    _image_map_from_payload,
    _is_direct_image_url,
    _normalize,
    live_listing_search,
)
from app.listings.repository import ListingRepository
from app.models import Listing


def make_listing(index: int, band: str, mode: str = "RENT") -> Listing:
    return Listing(
        id=f"bds-test-{index}",
        neighborhood_id="hcmc",
        title=f"Real sourced listing {index}",
        transaction_mode=mode,
        price_vnd={
            "LOW": 8_000_000,
            "MEDIUM": 18_000_000,
            "HIGH": 40_000_000,
            "ULTRA_HIGH": 80_000_000,
        }[band],
        price_usd=500,
        price_band=band,
        district="Ho Chi Minh City",
        property_type="Apartment",
        image_url=f"https://file4.batdongsan.com.vn/test-listing-{index}.jpg",
        source_url=f"https://batdongsan.com.vn/test-listing-{index}",
        demo=False,
    )


def test_sqlite_catalog_persists_and_balances_price_bands(tmp_path: Path):
    database = tmp_path / "catalog.db"
    repository = ListingRepository(database)
    repository.mark_attempt("RENT")
    repository.save_success(
        "RENT",
        [
            make_listing(1, "HIGH"),
            make_listing(2, "HIGH"),
            make_listing(3, "LOW"),
            make_listing(4, "ULTRA_HIGH"),
        ],
    )

    reopened = ListingRepository(database)
    items = reopened.list("RENT", 4)
    assert len(items) == 4
    assert [item.price_band for item in items[:3]] == ["LOW", "HIGH", "ULTRA_HIGH"]
    assert reopened.status("RENT")["due"] is False


def test_hundred_item_catalog_requires_real_core_band_coverage(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LISTING_MIN_PER_CORE_BAND", "20")
    catalog = ListingCatalog(ListingRepository(tmp_path / "catalog.db"))
    balanced = [
        make_listing(index, band)
        for index, band in enumerate(
            ["LOW"] * 20 + ["MEDIUM"] * 20 + ["HIGH"] * 20 + ["ULTRA_HIGH"] * 40
        )
    ]
    thin_low = [item.model_copy(update={"price_band": "ULTRA_HIGH"}) for item in balanced[:2]] + balanced[2:]

    assert catalog.is_complete(balanced, 100) is True
    assert catalog.is_complete(thin_low, 100) is False


@pytest.mark.asyncio
async def test_saved_catalog_does_not_call_gemini_again(tmp_path: Path, monkeypatch):
    repository = ListingRepository(tmp_path / "catalog.db")
    repository.mark_attempt("RENT")
    repository.save_success("RENT", [make_listing(1, "LOW")])
    catalog = ListingCatalog(repository)

    async def unexpected_search(*args, **kwargs):
        raise AssertionError("A saved catalog must not call Gemini before the weekly window.")

    monkeypatch.setattr(live_listing_search, "search", unexpected_search)

    items = await catalog.listings("RENT", 100)
    guarded_items = await catalog.refresh_if_due("RENT", 100)

    assert [item.id for item in items] == ["bds-test-1"]
    assert [item.id for item in guarded_items] == ["bds-test-1"]


def test_failed_attempt_is_rate_limited_for_a_week(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LISTING_REFRESH_HOURS", "168")
    repository = ListingRepository(tmp_path / "catalog.db")
    state = repository.mark_failure("BUY", "Provider temporarily unavailable")

    attempted_at = datetime.fromisoformat(state["last_attempt_at"])
    next_refresh_at = datetime.fromisoformat(state["next_refresh_at"])

    assert state["due"] is False
    assert next_refresh_at - attempted_at == timedelta(days=7)


@pytest.mark.asyncio
async def test_hundred_item_refresh_is_split_into_ten_item_batches(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LIVE_LISTING_BATCH_SIZE", "10")
    monkeypatch.setenv("LIVE_LISTING_SEARCH_COOLDOWN_SECONDS", "0")
    search = GeminiLiveListingSearch()
    calls: list[tuple[str, int, int]] = []

    async def fake_search_band(mode, band, target, batch_index=0, excluded_urls=()):
        calls.append((band, target, batch_index))
        offset = len(calls) * 100
        return [make_listing(offset + index, band, mode) for index in range(target)]

    monkeypatch.setattr(search, "_search_band", fake_search_band)
    items = await search.search("BUY", 100, refresh=True)

    assert len(items) == 100
    assert len(calls) == 12
    assert max(target for _, target, _ in calls) == 10
    assert {band: sum(item.price_band == band for item in items) for band in ("LOW", "MEDIUM", "HIGH", "ULTRA_HIGH")} == {
        "LOW": 25,
        "MEDIUM": 25,
        "HIGH": 25,
        "ULTRA_HIGH": 25,
    }


def test_listing_normalization_requires_english_text_and_direct_image():
    raw = {
        "title": "Two-bedroom apartment with river view",
        "price_vnd": 25_000_000,
        "district": "District 7",
        "address": "Nguyen Huu Tho Street, District 7",
        "property_type": "Apartment",
        "image_url": "https://file4.batdongsan.com.vn/property-123.jpg",
        "source_url": "https://batdongsan.com.vn/cho-thue-can-ho/property-pr12345678",
        "source_title": "Two-bedroom river-view apartment",
    }
    normalized = _normalize(raw, "RENT", set())
    assert normalized is not None
    assert normalized.price_usd > 0
    assert normalized.image_url.endswith(".jpg")

    assert _normalize({**raw, "image_url": ""}, "RENT", set()) is None
    assert _normalize({**raw, "title": "Căn hộ cho thuê ven sông"}, "RENT", set()) is None

    priced_title = _normalize(
        {**raw, "title": "Two-bedroom apartment, 25 Million VND/Month"}, "RENT", set()
    )
    assert priced_title is not None
    assert priced_title.title == "Two-bedroom apartment"


def test_image_enrichment_accepts_only_requested_batdongsan_photos():
    source_url = "https://batdongsan.com.vn/cho-thue-can-ho/property-123"
    requested = {source_url}
    payload = {
        "images": [
            {
                "source_url": source_url,
                "image_url": "https://cdn.batdongsan.com.vn/crop/540x282/property-123.webp",
            },
            {
                "source_url": "https://batdongsan.com.vn/not-requested",
                "image_url": "https://cdn.batdongsan.com.vn/not-requested.jpg",
            },
        ]
    }

    assert _image_map_from_payload(payload, requested) == {
        source_url: "https://cdn.batdongsan.com.vn/crop/540x282/property-123.webp"
    }
    assert _is_direct_image_url("https://cdn.batdongsan.com.vn/property.jpg") is True
    assert _is_direct_image_url("https://example.com/property.jpg") is True
    assert _is_direct_image_url("http://example.com/property.jpg") is False
    assert _is_direct_image_url("https://batdongsan.com.vn/property-page") is False
