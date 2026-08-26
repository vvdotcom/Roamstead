from __future__ import annotations

import argparse
import asyncio
import os

from app.listings.catalog import listing_catalog
from app.listings.images import (
    cache_listing_gallery,
    cached_gallery_paths,
    minimum_gallery_size,
    prune_cached_gallery,
)
from app.listings.live_search import GeminiLiveListingSearch
from app.listings.repository import ListingRepository


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ground and locally cache exact-listing property photo galleries."
    )
    parser.add_argument("--mode", required=True, choices=("BUY", "RENT"))
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--listing-id")
    parser.add_argument("--min-images", type=int, default=minimum_gallery_size())
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    shards = max(1, args.shards)
    shard = max(0, min(shards - 1, args.shard))
    repository = ListingRepository()
    search = GeminiLiveListingSearch()
    items = sorted(repository.list(args.mode, max(1, min(100, args.limit))), key=lambda item: item.id)
    if args.listing_id:
        exact = repository.get(args.listing_id)
        items = [exact] if exact and exact.transaction_mode == args.mode else []
    selected = items[shard::shards]
    gallery_limit = max(1, min(20, int(os.getenv("LISTING_GALLERY_MAX_IMAGES", "10"))))
    minimum = max(1, min(gallery_limit, args.min_images))

    for position, item in enumerate(selected, 1):
        local_count = len(cached_gallery_paths(item.id))
        if not args.force and len(item.image_urls) >= minimum and local_count >= minimum:
            print(
                f"{args.mode} shard {shard + 1}/{shards} {position}/{len(selected)} "
                f"skip {item.id}: {local_count} photos",
                flush=True,
            )
            continue
        try:
            urls = (
                await search.filter_gallery_urls_by_upload_batch(item, item.image_urls)
                if args.audit_only
                else await search.find_gallery_urls(item, gallery_limit)
            )
            updated = await cache_listing_gallery(item, urls)
            if args.audit_only and item.image_urls and not updated:
                prune_cached_gallery(item.id, 1)
                updated = item.model_copy(update={"image_urls": [item.image_url]})
            if updated:
                repository.save_progress(args.mode, [updated])
            count = len(cached_gallery_paths(item.id))
            print(
                f"{args.mode} shard {shard + 1}/{shards} {position}/{len(selected)} "
                f"{item.id}: {'audited' if args.audit_only else 'grounded'}={len(urls)} cached={count}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"{args.mode} shard {shard + 1}/{shards} {position}/{len(selected)} "
                f"{item.id}: {type(exc).__name__}: {str(exc)[:180]}",
                flush=True,
            )

    all_items = repository.list(args.mode, 100)
    if listing_catalog.is_complete(all_items, listing_catalog.target_size()):
        repository.save_success(args.mode, all_items)
    ready = sum(len(cached_gallery_paths(item.id)) >= minimum for item in all_items)
    print(f"{args.mode}: {ready}/{len(all_items)} listings have at least {minimum} photos", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
