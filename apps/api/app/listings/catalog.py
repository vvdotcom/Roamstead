from __future__ import annotations

import asyncio
import os
from typing import Any

from ..cloud import cloud_enabled, firestore_primary, persist_listing_catalog, upload_listing_images
from ..models import Listing
from .live_search import (
    LiveListingConfigurationError,
    LiveListingSearchError,
    live_listing_search,
)
from .images import (
    cache_listing_gallery,
    cache_listing_images,
    cached_gallery_paths,
    minimum_gallery_size,
)
from .repository import ListingRepository


class ListingCatalog:
    """Coordinates one grounded refresh per mode per seven-day window."""

    def __init__(self, repository: ListingRepository | None = None) -> None:
        self.repository = repository or ListingRepository()
        self._locks = {"BUY": asyncio.Lock(), "RENT": asyncio.Lock()}
        self._refreshing = {"BUY": False, "RENT": False}
        self._gallery_refreshing = {"BUY": False, "RENT": False}
        self._gallery_error: dict[str, str | None] = {"BUY": None, "RENT": None}
        self._firestore_mirrored = False
        self._firestore_error: str | None = None

    @staticmethod
    def target_size() -> int:
        return max(25, min(100, int(os.getenv("LISTING_CATALOG_TARGET", "100"))))

    @staticmethod
    def minimum_core_band(limit: int) -> int:
        configured = max(1, int(os.getenv("LISTING_MIN_PER_CORE_BAND", "20")))
        return min(25, max(configured, limit // 5))

    def is_complete(self, items: list[Listing], limit: int) -> bool:
        if limit < 25:
            return len(items) >= limit
        minimum = self.minimum_core_band(limit)
        return len(items) >= limit and all(
            sum(item.price_band == band for item in items) >= minimum
            for band in ("LOW", "MEDIUM", "HIGH")
        )

    async def listings(
        self,
        mode: str,
        limit: int = 100,
        city: str = "Ho Chi Minh City",
    ) -> list[Listing]:
        stored = self.repository.list(mode, limit, city)
        if stored:
            return stored

        # Expansion markets are intentionally curated once and served from the
        # database. Browser traffic must never trigger repeated provider calls.
        if city != "Ho Chi Minh City":
            raise LiveListingSearchError(
                f"The verified {city} catalog is not available in the database yet."
            )

        state = self.repository.status(mode)
        if not state["due"]:
            error = state["last_error"] or "The first weekly catalog refresh has not completed."
            raise LiveListingSearchError(error)
        return await self.refresh_if_due(mode, limit)

    async def refresh_if_due(self, mode: str, limit: int = 100) -> list[Listing]:
        async with self._locks[mode]:
            state = self.repository.status(mode)
            stored = self.repository.list(mode, limit)
            # Any saved inventory is served until the next weekly window. An
            # incomplete catalog must not trigger extra Gemini calls between
            # scheduled refreshes.
            if not state["due"] and stored:
                return stored
            if not state["due"] and not stored:
                error = state["last_error"] or "The weekly catalog refresh is still pending."
                raise LiveListingSearchError(error)

            if not live_listing_search.configured:
                raise LiveListingConfigurationError(
                    "The catalog is empty and its weekly refresh requires GEMINI_API_KEY or Vertex AI credentials. "
                    "No synthetic listings are used."
                )

            self._refreshing[mode] = True
            self.repository.mark_attempt(mode)
            try:
                async def persist_batch(batch: list[Listing]) -> list[Listing]:
                    cached = await cache_listing_images(batch)
                    self.repository.save_progress(mode, cached)
                    return cached

                existing = self.repository.list(mode, 400)
                await live_listing_search.search(
                    mode,
                    limit,
                    refresh=True,
                    existing_items=existing,
                    on_batch=persist_batch,
                )
                stored = self.repository.list(mode, limit)
                band_counts = {
                    band: sum(item.price_band == band for item in stored)
                    for band in ("LOW", "MEDIUM", "HIGH", "ULTRA_HIGH")
                }
                minimum_core_band = self.minimum_core_band(limit)
                core_balanced = all(band_counts[band] >= minimum_core_band for band in ("LOW", "MEDIUM", "HIGH"))
                if len(stored) < limit or not core_balanced:
                    self.repository.mark_failure(
                        mode,
                        f"Catalog progress: {len(stored)}/{limit} locally imaged listings; bands {band_counts}.",
                    )
                    return stored

                refresh_state = self.repository.save_success(mode, stored)
                await self._mirror_to_firestore(mode, stored, refresh_state)
                return stored
            except (LiveListingConfigurationError, LiveListingSearchError) as exc:
                self.repository.mark_failure(mode, str(exc))
                stored = self.repository.list(mode, limit)
                if stored:
                    return stored
                raise
            except Exception as exc:
                message = f"Weekly listing refresh failed: {exc}"
                self.repository.mark_failure(mode, message)
                stored = self.repository.list(mode, limit)
                if stored:
                    return stored
                raise LiveListingSearchError(message) from exc
            finally:
                self._refreshing[mode] = False

    async def _mirror_to_firestore(
        self,
        mode: str,
        items: list[Listing],
        refresh_state: dict[str, Any],
    ) -> None:
        if not cloud_enabled():
            return
        try:
            self._firestore_mirrored = await asyncio.to_thread(
                persist_listing_catalog,
                mode,
                [item.model_dump(mode="json") for item in items],
                refresh_state,
            )
            for item in items:
                paths = [str(path) for path in cached_gallery_paths(item.id)]
                if paths:
                    await asyncio.to_thread(upload_listing_images, item.id, paths)
            self._firestore_error = None
        except Exception as exc:
            # SQLite remains the durable local source when ADC is unavailable.
            self._firestore_mirrored = False
            self._firestore_error = str(exc)[:300]

    async def refresh_all_due(self) -> None:
        # Run modes sequentially so one API key is not flooded with eight or
        # more simultaneous grounded-search calls.
        modes = ("RENT", "BUY")
        target = self.target_size()
        for index, mode in enumerate(modes):
            existing = self.repository.list(mode, target)
            needed_refresh = self.repository.status(mode)["due"] or not self.is_complete(existing, target)
            try:
                await self.refresh_if_due(mode, target)
            except (LiveListingConfigurationError, LiveListingSearchError):
                pass
            await self.enrich_galleries(mode, target)
            if needed_refresh and index < len(modes) - 1:
                await asyncio.sleep(max(0, int(os.getenv("LISTING_MODE_COOLDOWN_SECONDS", "60"))))

    async def enrich_galleries(self, mode: str, limit: int = 100) -> None:
        """Resume exact-listing gallery retrieval until every public item is ready."""
        if not live_listing_search.configured or self._gallery_refreshing[mode]:
            return
        minimum = minimum_gallery_size()
        pending = [
            item
            for item in self.repository.list(mode, limit)
            if len(cached_gallery_paths(item.id)) < minimum
        ]
        if not pending:
            self._gallery_error[mode] = None
            return

        self._gallery_refreshing[mode] = True
        try:
            for item in pending:
                try:
                    urls = await live_listing_search.find_gallery_urls(item)
                    updated = await cache_listing_gallery(item, urls)
                    if updated:
                        self.repository.save_progress(mode, [updated])
                except Exception as exc:
                    # Quota and transient provider errors should end this pass,
                    # not discard its earlier progress or flood Gemini retries.
                    self._gallery_error[mode] = f"{type(exc).__name__}: {str(exc)[:240]}"
                    break
            else:
                self._gallery_error[mode] = None
        finally:
            self._gallery_refreshing[mode] = False

    async def run_weekly_scheduler(self) -> None:
        check_seconds = max(60, int(os.getenv("LISTING_SCHEDULER_CHECK_SECONDS", "3600")))
        while True:
            await self.refresh_all_due()
            await asyncio.sleep(check_seconds)

    def status(self) -> dict[str, Any]:
        target = self.target_size()
        modes: dict[str, Any] = {}
        for mode in ("BUY", "RENT"):
            state = self.repository.status(mode)
            items = self.repository.list(mode, target)
            gallery_counts = [len(cached_gallery_paths(item.id)) for item in items]
            publishable = sum(count >= minimum_gallery_size() for count in gallery_counts)
            modes[mode] = {
                **state,
                "due": state["due"] or not self.is_complete(items, target),
                "refreshing": self._refreshing[mode],
                "gallery_refreshing": self._gallery_refreshing[mode],
                "gallery_error": self._gallery_error[mode],
                "publishable_with_required_photos": publishable,
                "pending_gallery_enrichment": len(items) - publishable,
            }
        markets = {
            city: {
                mode: self.repository.status(mode, city)["count"]
                for mode in ("BUY", "RENT")
            }
            for city in ("Ho Chi Minh City", "Bangkok", "Kuala Lumpur")
        }
        return {
            "storage": (
                "Firestore primary + ephemeral SQLite cache"
                if firestore_primary()
                else "SQLite + Firestore mirror" if cloud_enabled() else "SQLite"
            ),
            "database_path": str(self.repository.path),
            "refresh_interval_hours": max(1, int(os.getenv("LISTING_REFRESH_HOURS", "168"))),
            "target_per_mode": target,
            "minimum_photos_per_public_listing": minimum_gallery_size(),
            "firestore_configured": cloud_enabled(),
            "firestore_mirrored": self._firestore_mirrored,
            "firestore_error": self._firestore_error,
            "modes": modes,
            "markets": markets,
        }

    def get(self, listing_id: str) -> Listing | None:
        return self.repository.get(listing_id)

    def cached_items(self) -> list[Listing]:
        return self.repository.all_items()


listing_catalog = ListingCatalog()
