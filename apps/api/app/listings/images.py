from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

import httpx

from ..cloud import cloud_listing_image_count
from ..models import Listing


_MODULE_PATH = Path(__file__).resolve()
PROJECT_ROOT = _MODULE_PATH.parents[4] if len(_MODULE_PATH.parents) > 4 else Path.cwd()
IMAGE_ROOT = PROJECT_ROOT / "data" / "listing_images"
IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def minimum_gallery_size() -> int:
    return max(1, min(20, int(os.getenv("LISTING_MIN_PUBLISHABLE_PHOTOS", "1"))))


def has_publishable_gallery(listing_id: str) -> bool:
    return available_gallery_size(listing_id) >= minimum_gallery_size()


def available_gallery_size(listing_id: str) -> int:
    local_count = len(cached_gallery_paths(listing_id))
    return local_count or cloud_listing_image_count(listing_id)


def public_image_url(listing_id: str, image_index: int = 0) -> str:
    suffix = "" if image_index == 0 else f"/{image_index}"
    return f"/api/v1/listing-images/{listing_id}{suffix}"


def cached_image_path(listing_id: str, image_index: int = 0) -> Path | None:
    stem = listing_id if image_index == 0 else f"{listing_id}--{image_index}"
    for extension in IMAGE_TYPES.values():
        candidate = IMAGE_ROOT / f"{stem}{extension}"
        if candidate.is_file() and candidate.stat().st_size >= 2_048:
            return candidate
    return None


def cached_gallery_paths(listing_id: str) -> list[Path]:
    paths: list[Path] = []
    index = 0
    while path := cached_image_path(listing_id, index):
        paths.append(path)
        index += 1
    return paths


def prune_cached_gallery(listing_id: str, keep: int = 1) -> None:
    index = max(1, keep)
    while stale_path := cached_image_path(listing_id, index):
        stale_path.unlink()
        index += 1


def image_media_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")


async def _cache_image_url(
    listing_id: str,
    image_url: str,
    image_index: int,
    *,
    replace: bool = False,
) -> Path | None:
    cached = cached_image_path(listing_id, image_index)
    if cached and not replace:
        return cached

    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=max(10.0, float(os.getenv("LISTING_IMAGE_DOWNLOAD_TIMEOUT_SECONDS", "30"))),
            headers={"User-Agent": "Mozilla/5.0 (compatible; Roamstead/1.0)"},
        ) as client:
            response = await client.get(image_url)
    except httpx.HTTPError:
        return None

    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    extension = IMAGE_TYPES.get(content_type)
    maximum_bytes = max(1_000_000, int(os.getenv("LISTING_IMAGE_MAX_BYTES", "10000000")))
    if response.status_code != 200 or not extension or not 2_048 <= len(response.content) <= maximum_bytes:
        return None

    content_hash = sha256(response.content).digest()
    target_stem = listing_id if image_index == 0 else f"{listing_id}--{image_index}"
    for existing in IMAGE_ROOT.iterdir():
        if not existing.is_file() or existing.suffix.lower() not in IMAGE_TYPES.values():
            continue
        # Re-running a gallery search for one listing is idempotent. Across
        # different listings, identical bytes are still rejected so a generic
        # project image cannot make unrelated homes look the same.
        if existing.stem == target_stem:
            continue
        try:
            if sha256(existing.read_bytes()).digest() == content_hash:
                return None
        except OSError:
            continue

    stem = target_stem
    destination = IMAGE_ROOT / f"{stem}{extension}"
    temporary = IMAGE_ROOT / f"{stem}{extension}.partial"
    temporary.write_bytes(response.content)
    temporary.replace(destination)
    if replace:
        for old_extension in IMAGE_TYPES.values():
            old_path = IMAGE_ROOT / f"{stem}{old_extension}"
            if old_path != destination and old_path.is_file():
                old_path.unlink()
    return destination


async def cache_listing_image(listing: Listing) -> Path | None:
    cached = cached_image_path(listing.id)
    if cached:
        return cached
    return await _cache_image_url(listing.id, listing.image_url, 0)


async def cache_listing_gallery(listing: Listing, image_urls: list[str]) -> Listing | None:
    maximum = max(1, min(20, int(os.getenv("LISTING_GALLERY_MAX_IMAGES", "10"))))
    candidates = list(dict.fromkeys(url.strip() for url in image_urls if url.strip()))[:maximum]
    if not candidates:
        return None

    accepted_urls: list[str] = []
    accepted_paths: list[Path] = []
    for candidate in candidates:
        index = len(accepted_urls)
        path = await _cache_image_url(listing.id, candidate, index, replace=True)
        if path:
            accepted_urls.append(candidate)
            accepted_paths.append(path)

    if not accepted_urls:
        return None

    # Remove stale tail images when a later refresh returns a shorter gallery.
    stale_index = len(accepted_paths)
    while stale_path := cached_image_path(listing.id, stale_index):
        stale_path.unlink()
        stale_index += 1

    return listing.model_copy(
        update={"image_url": accepted_urls[0], "image_urls": accepted_urls}
    )


async def cache_listing_images(items: list[Listing]) -> list[Listing]:
    accepted: list[Listing] = []
    # Keep downloads sequential to avoid looking like a burst scraper and to
    # make validation behavior deterministic during the catalog build.
    for item in items:
        if await cache_listing_image(item):
            accepted.append(item)
    return accepted
