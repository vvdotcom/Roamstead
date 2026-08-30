from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

from app.evaluation import create_evaluation_report, trajectory_score
from app.evaluation_artifacts import curated_failed_run_ids, persist_evaluation_artifact
from app.listing_fit import _hard_constraint_failure
from app.listings.catalog import listing_catalog
from app.models import DecisionProfile


ROOT = Path(__file__).resolve().parents[1]
EVALSET = ROOT / "evaluation_data" / "preference_interpreter.evalset.json"
CONFIG = ROOT / "evaluation_data" / "test_config.json"
AGENT = ROOT / "eval_agents" / "preference_interpreter"


def run_adk_eval() -> tuple[float, float]:
    command = [
        "adk",
        "eval",
        str(AGENT),
        str(EVALSET),
        f"--config_file_path={CONFIG}",
        "--print_detailed_results",
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    combined = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        raise RuntimeError(f"ADK evaluation failed with exit code {completed.returncode}: {combined[-2000:]}")

    scores: dict[str, list[float]] = {}
    for metric, score in re.findall(
        r"Metric:\s*([A-Za-z0-9_]+).*?Score:\s*([0-9.]+)", combined, flags=re.IGNORECASE | re.DOTALL
    ):
        scores.setdefault(metric.casefold(), []).append(float(score))
    response_values = scores.get("final_response_match_v2") or scores.get("response_match_score") or []
    trajectory_values = scores.get("tool_trajectory_avg_score") or []
    if not response_values or not trajectory_values:
        raise RuntimeError("ADK evaluation completed without parseable response and trajectory scores")
    return sum(response_values) / len(response_values), sum(trajectory_values) / len(trajectory_values)


def proof_run_gates(run_id: str) -> tuple[dict[str, bool], float]:
    repository = listing_catalog.repository
    run = repository.get_agent_run(run_id)
    brief = repository.get_decision_brief(run_id)
    if not run or not brief or brief.status != "COMPLETED":
        raise RuntimeError("The proof run must be a completed persisted Decision Brief")
    profile = DecisionProfile.model_validate(run.input_payload["profile"])
    events = repository.list_agent_events(run_id)
    actors = [event.actor for event in events]
    expected = [
        "LockDecisionInputs",
        "RecalculateFitScores",
        "SemanticMemoryTool",
        "ListingAnalyst",
        "CriticJoin",
        "EvidenceVerifier",
        "CorrectionRouter",
        "BriefComposer",
        "PersistDecisionBrief",
        "DatabaseWriter",
    ]
    trajectory = trajectory_score(actors, expected)
    actor_position = {actor: min(i for i, value in enumerate(actors) if value == actor) for actor in set(actors)}
    critic_starts = [
        event
        for event in events
        if event.event_type == "SPECIALIST_STARTED"
        and event.actor in {"VisualEvidenceCritic", "MemoryConsistencyCritic"}
        and event.parallel_group == "CRITICS_1"
    ]
    join_position = actor_position.get("CriticJoin", -1)
    listings = [listing_catalog.get(item.listing_id) for item in brief.properties]
    memories = brief.memory_context.matches if brief.memory_context else []
    gates = {
        "approval_required": brief.profile_version == profile.version,
        "hard_filters_preserved": all(
            item is not None and _hard_constraint_failure(item, profile) is None for item in listings
        ),
        "profile_memory_isolated": all(
            (memory := repository.get_semantic_memory(match.memory_id)) is not None
            and memory.profile_id == profile.profile_id
            for match in memories
        ),
        "real_data_only": all(
            item is not None
            and item.demo is False
            and item.source_domain == "batdongsan.com.vn"
            and item.source_url.startswith("https://batdongsan.com.vn/")
            for item in listings
        ),
        "parallel_critics_joined": len({item.actor for item in critic_starts}) == 2
        and join_position >= 0
        and all(actors.index(item.actor) < join_position for item in critic_starts),
        "correction_limit": len([item for item in events if item.event_type == "CORRECTION_REQUESTED"]) <= 1,
        "no_vector_exposure": '"embedding"' not in brief.model_dump_json(),
        "successful_models": not brief.degraded
        and bool(brief.visual_audit and brief.visual_audit.succeeded)
        and bool(brief.memory_audit and brief.memory_audit.succeeded)
        and bool(brief.memory_context and brief.memory_context.status == "READY"),
    }
    return gates, trajectory


def main() -> None:
    parser = argparse.ArgumentParser(description="Run and persist Roamstead's ADK release evaluation.")
    parser.add_argument("--proof-run-id", default=os.getenv("ROAMSTEAD_EVAL_PROOF_RUN_ID", ""))
    parser.add_argument("--response-score", type=float, default=None)
    parser.add_argument("--trajectory-score", type=float, default=None)
    args = parser.parse_args()
    if not args.proof_run_id:
        raise SystemExit("Provide --proof-run-id from a successful non-degraded production Decision Brief")

    gates, runtime_trajectory = proof_run_gates(args.proof_run_id)
    if args.response_score is None or args.trajectory_score is None:
        response_score, adk_trajectory = run_adk_eval()
    else:
        response_score, adk_trajectory = args.response_score, args.trajectory_score
    report = create_evaluation_report(
        response_score=response_score,
        trajectory_score=min(runtime_trajectory, adk_trajectory),
        hard_gate_results=gates,
        source="CLOUD_RUN_JOB" if os.getenv("CLOUD_RUN_JOB") or os.getenv("K_SERVICE") else "ADK_EVAL",
    )
    listing_catalog.repository.save_evaluation_report(report)
    failed_run_ids = curated_failed_run_ids() if os.getenv("CLOUD_RUN_JOB") or os.getenv("K_SERVICE") else []
    artifact_uri = persist_evaluation_artifact(
        "reports",
        report.id,
        {
            "report": report.model_dump(mode="json"),
            "proof_run_id": args.proof_run_id,
            "curated_failed_run_ids": failed_run_ids,
            "privacy": "sanitized IDs and aggregate metrics only",
        },
    )
    print(report.model_dump_json(indent=2))
    if artifact_uri:
        print(f"Private integrity-attested report: {artifact_uri}")
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
