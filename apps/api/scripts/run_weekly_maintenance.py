"""Cost-bounded weekly work: approved Decision Watches, then catalog refresh."""

from __future__ import annotations

import asyncio
import json
import os

from app.cloud import publish_event
from app.decision_watches import decision_watch_service
from app.listings.catalog import listing_catalog


async def main() -> None:
    watches = await decision_watch_service.process_due()
    output: dict[str, object] = {
        "decision_watches_processed": len(watches),
        "watch_ids": [watch.id for watch in watches],
    }
    if os.getenv("ENABLE_CATALOG_REFRESH_IN_MAINTENANCE", "1") == "1":
        try:
            await listing_catalog.refresh_all_due()
            output["catalog"] = listing_catalog.status()
            publish_event("listing_catalog.completed", output["catalog"])
        except Exception as exc:
            output["catalog_error"] = {
                "error_type": type(exc).__name__,
                "message": str(exc)[:300],
            }
            publish_event("listing_catalog.failed", output["catalog_error"])
            raise
    publish_event("weekly_maintenance.completed", output)
    print(json.dumps(output, default=str))


if __name__ == "__main__":
    asyncio.run(main())
