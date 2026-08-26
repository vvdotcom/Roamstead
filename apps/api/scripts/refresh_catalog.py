from __future__ import annotations

import argparse
import asyncio
import os

from app.listings.catalog import listing_catalog
from app.cloud import publish_event
from app.listings.images import cache_listing_images
from app.listings.live_search import GeminiLiveListingSearch, PRICE_BANDS
from app.listings.repository import ListingRepository


async def backfill_band(mode: str, band: str, target: int, batches: int) -> int:
    """Fill a thin price band while preserving the same live-data checks."""
    repository = ListingRepository()
    search = GeminiLiveListingSearch()
    batch_size = max(1, min(10, int(os.getenv("LIVE_LISTING_BATCH_SIZE", "6"))))
    for batch_index in range(batches):
        existing = [item for item in repository.list(mode, 100) if item.price_band == band]
        if len(existing) >= target:
            break
        try:
            found = await search._search_band(
                mode,
                band,
                min(batch_size, target - len(existing)),
                batch_index=len(existing) + batch_index,
                excluded_urls=tuple(sorted(item.source_url for item in existing)),
            )
        except Exception as exc:
            print(
                f"{mode} {band} batch {batch_index + 1} skipped: "
                f"{type(exc).__name__}: {str(exc)[:160]}",
                flush=True,
            )
            await asyncio.sleep(2)
            continue
        accepted = await cache_listing_images(found)
        repository.save_progress(mode, accepted)
        current = len([item for item in repository.list(mode, 100) if item.price_band == band])
        print(
            f"{mode} {band} batch {batch_index + 1}: "
            f"found={len(found)} cached={len(accepted)} total={current}/{target}",
            flush=True,
        )
    all_items = repository.list(mode, 100)
    catalog_target = listing_catalog.target_size()
    if listing_catalog.is_complete(all_items, catalog_target):
        repository.save_success(mode, all_items)
    return len([item for item in all_items if item.price_band == band])


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build one Roamstead listing catalog mode.")
    parser.add_argument("--mode", required=True, choices=("BUY", "RENT", "ALL"))
    parser.add_argument("--band", choices=tuple(PRICE_BANDS["BUY"]), help="Backfill only one price band")
    parser.add_argument("--band-target", type=int, default=25)
    parser.add_argument("--batches", type=int, default=12)
    parser.add_argument("--target", type=int, default=listing_catalog.target_size())
    args = parser.parse_args()
    if args.mode == "ALL":
        try:
            await listing_catalog.refresh_all_due()
            status = listing_catalog.status()
            publish_event("listing_catalog.completed", status)
            print(f"Weekly catalog job completed: {status['modes']}")
        except Exception as exc:
            publish_event("listing_catalog.failed", {"error_type": type(exc).__name__, "message": str(exc)[:300]})
            raise
        return
    if args.band:
        count = await backfill_band(
            args.mode,
            args.band,
            max(1, min(25, args.band_target)),
            max(1, min(24, args.batches)),
        )
        print(f"{args.mode} {args.band}: {count}/{args.band_target} locally imaged listings")
        return
    target = max(25, min(100, args.target))
    items = await listing_catalog.refresh_if_due(args.mode, target)
    print(f"{args.mode}: {len(items)}/{target} locally imaged listings")


if __name__ == "__main__":
    asyncio.run(main())
