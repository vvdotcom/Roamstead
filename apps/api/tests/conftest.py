from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_TEST_DATA_DIRECTORY = Path(tempfile.mkdtemp(prefix="roamstead-api-tests-"))
os.environ["ROAMSTEAD_DATABASE_PATH"] = str(_TEST_DATA_DIRECTORY / "roamstead.db")


from app.listings.repository import ListingRepository  # noqa: E402
from app.listings import images as listing_images  # noqa: E402
from app.models import Listing  # noqa: E402
from PIL import Image  # noqa: E402


listing_images.IMAGE_ROOT = _TEST_DATA_DIRECTORY / "listing_images"
listing_images.IMAGE_ROOT.mkdir(parents=True, exist_ok=True)


def _catalog_listing(mode: str, index: int) -> Listing:
    neighborhoods = (
        ("thu-thiem", "Thu Duc City"),
        ("binh-thanh", "Binh Thanh District"),
        ("phu-my-hung", "District 7"),
        ("nha-be", "Nha Be District"),
    )
    neighborhood_id, district = neighborhoods[index % len(neighborhoods)]
    bands = ("LOW", "MEDIUM", "HIGH", "ULTRA_HIGH")
    buy_prices = (85_000, 110_000, 140_000, 165_000, 125_000, 150_000)
    rent_prices = (450, 650, 850, 1_050, 1_250, 1_400)
    price_usd = (buy_prices if mode == "BUY" else rent_prices)[index]
    slug = "buy" if mode == "BUY" else "rent"
    image_url = f"https://file4.batdongsan.com.vn/ci-{slug}-{index}.jpg"
    return Listing(
        id=f"bds-ci-{slug}-{index}",
        neighborhood_id=neighborhood_id,
        title=f"CI sourced {mode.casefold()} apartment {index + 1}",
        transaction_mode=mode,
        price_local=price_usd * 25_000,
        price_vnd=price_usd * 25_000,
        price_usd=price_usd,
        exchange_rate_per_usd=25_000,
        exchange_rate_date="2026-08-30",
        price_band=bands[index % len(bands)],
        district=district,
        address=f"Fixture address {index + 1}, {district}",
        beds=1 + (index % 3),
        baths=1 + (index % 2),
        area_sqm=45 + (index * 12),
        image_url=image_url,
        image_urls=[image_url],
        hospital_minutes=8 + index,
        waterfront_minutes=4 + index,
        international_school_minutes_estimate=10 + index,
        food_minutes_estimate=5 + index,
        property_type="Apartment",
        source_url=f"https://batdongsan.com.vn/ci-{slug}-{index}",
        source_title=f"CI source {slug} {index + 1}",
        demo=False,
    )


_repository = ListingRepository()
for _mode in ("BUY", "RENT"):
    _items = [_catalog_listing(_mode, index) for index in range(6)]
    for _index, _item in enumerate(_items):
        _image = Image.effect_noise((256, 256), 80 + _index).convert("RGB")
        _image.save(listing_images.IMAGE_ROOT / f"{_item.id}.jpg", quality=90)
    _repository.mark_attempt(_mode)
    _repository.save_success(_mode, _items)


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def]
    shutil.rmtree(_TEST_DATA_DIRECTORY, ignore_errors=True)
