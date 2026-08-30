from __future__ import annotations

import argparse
from datetime import datetime, timezone

from app.evaluation import propose_prompt_revision
from app.evaluation_artifacts import persist_evaluation_artifact
from app.listings.catalog import listing_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or explicitly approve an evaluated prompt candidate.")
    parser.add_argument("baseline_report_id")
    parser.add_argument("candidate_report_id")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()

    repository = listing_catalog.repository
    baseline = repository.get_evaluation_report(args.baseline_report_id)
    candidate_report = repository.get_evaluation_report(args.candidate_report_id)
    if not baseline or not candidate_report:
        raise SystemExit("Both persisted evaluation reports are required")
    candidate = propose_prompt_revision(baseline, candidate_report)
    if args.approve:
        if not candidate.activation_allowed:
            raise SystemExit("Candidate failed improvement, regression, or hard-gate requirements")
        candidate.status = "APPROVED"
        candidate.decided_at = datetime.now(timezone.utc).isoformat()
    repository.save_prompt_revision_candidate(candidate)
    artifact_uri = persist_evaluation_artifact(
        "prompt-candidates",
        candidate.id,
        {
            "candidate": candidate.model_dump(mode="json"),
            "activation_contract": "explicit operator approval plus a new Cloud Run revision",
            "prompt_text_included": False,
        },
    )
    print(candidate.model_dump_json(indent=2))
    if artifact_uri:
        print(f"Private candidate metadata: {artifact_uri}")
    if args.approve:
        print(
            "Approval recorded. Activate only by deploying a new Cloud Run revision with "
            f"ROAMSTEAD_PROMPT_VERSION={candidate.candidate_prompt_version}."
        )


if __name__ == "__main__":
    main()
