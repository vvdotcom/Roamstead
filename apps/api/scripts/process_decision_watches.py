"""Run the bounded, scale-to-zero Decision Watch maintenance workload."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.decision_watches import decision_watch_service


async def _run(limit: int | None) -> int:
    completed = await decision_watch_service.process_due(limit)
    print(
        json.dumps(
            {
                "processed": len(completed),
                "watches": [
                    {
                        "id": watch.id,
                        "last_outcome": watch.last_outcome,
                        "revision_count": watch.revision_count,
                        "next_run_at": watch.next_run_at,
                    }
                    for watch in completed
                ],
            }
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    return asyncio.run(_run(args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
