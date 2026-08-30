from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable

from .models import EvaluationMetricResult, EvaluationReport, PromptRevisionCandidate


WORKFLOW_VERSION = "partner-coordinator-v2"
PROMPT_VERSION = "preference-interpreter-v1"
DATASET_VERSION = "workshop-eval-real-snapshot-v1"
DEVELOPMENT_CASES = 12
VALIDATION_CASES = 8
RESPONSE_THRESHOLD = 0.85
TRAJECTORY_THRESHOLD = 0.90
MINIMUM_COMPOSITE_IMPROVEMENT = 0.03
MAXIMUM_METRIC_REGRESSION = 0.02


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_evaluation_report(
    *,
    response_score: float,
    trajectory_score: float,
    hard_gate_results: dict[str, bool],
    workflow_version: str = WORKFLOW_VERSION,
    prompt_version: str = PROMPT_VERSION,
    dataset_version: str = DATASET_VERSION,
    source: str = "FIXTURE",
) -> EvaluationReport:
    """Create a reproducible sanitized report from ADK and hard-gate scores."""

    hard_gates_passed = bool(hard_gate_results) and all(hard_gate_results.values())
    metrics = [
        EvaluationMetricResult(
            name="response_quality",
            score=response_score,
            threshold=RESPONSE_THRESHOLD,
            passed=response_score >= RESPONSE_THRESHOLD,
            explanation="ADK response/rubric quality across the twenty-case real-snapshot set.",
        ),
        EvaluationMetricResult(
            name="tool_trajectory",
            score=trajectory_score,
            threshold=TRAJECTORY_THRESHOLD,
            passed=trajectory_score >= TRAJECTORY_THRESHOLD,
            explanation="Required workflow nodes, tools, ordering, joins, and correction limit.",
        ),
        EvaluationMetricResult(
            name="safety_and_real_data_gates",
            score=sum(hard_gate_results.values()) / len(hard_gate_results) if hard_gate_results else 0,
            threshold=1.0,
            passed=hard_gates_passed,
            explanation="Approval, hard-filter, provenance, profile-isolation, and no-synthetic-data gates.",
        ),
    ]
    payload = {
        "workflow_version": workflow_version,
        "prompt_version": prompt_version,
        "dataset_version": dataset_version,
        "metrics": [(item.name, item.score, item.passed) for item in metrics],
        "hard_gates": sorted(hard_gate_results.items()),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return EvaluationReport(
        id=f"eval-{digest}",
        workflow_version=workflow_version,
        prompt_version=prompt_version,
        dataset_version=dataset_version,
        development_case_count=DEVELOPMENT_CASES,
        validation_case_count=VALIDATION_CASES,
        hard_gates_passed=hard_gates_passed,
        passed=hard_gates_passed and all(item.passed for item in metrics),
        metrics=metrics,
        source=source,
        created_at=_now(),
    )


def propose_prompt_revision(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> PromptRevisionCandidate:
    """Apply the non-negotiable activation gates to an optimizer candidate."""

    baseline_scores = {item.name: item.score for item in baseline.metrics}
    candidate_scores = {item.name: item.score for item in candidate.metrics}
    shared = sorted(set(baseline_scores) & set(candidate_scores))
    baseline_composite = sum(baseline_scores[key] for key in shared) / len(shared) if shared else 0
    candidate_composite = sum(candidate_scores[key] for key in shared) / len(shared) if shared else 0
    regressions = [baseline_scores[key] - candidate_scores[key] for key in shared]
    maximum_regression = max([0.0, *regressions])
    improvement = candidate_composite - baseline_composite
    activation_allowed = bool(
        candidate.passed
        and candidate.hard_gates_passed
        and improvement >= MINIMUM_COMPOSITE_IMPROVEMENT
        and maximum_regression <= MAXIMUM_METRIC_REGRESSION
    )
    digest = hashlib.sha256(f"{baseline.id}:{candidate.id}".encode()).hexdigest()[:16]
    return PromptRevisionCandidate(
        id=f"prompt-candidate-{digest}",
        baseline_prompt_version=baseline.prompt_version,
        candidate_prompt_version=candidate.prompt_version,
        baseline_report_id=baseline.id,
        candidate_report_id=candidate.id,
        composite_improvement=round(improvement, 6),
        maximum_metric_regression=round(maximum_regression, 6),
        hard_gates_passed=candidate.hard_gates_passed,
        activation_allowed=activation_allowed,
    )


def trajectory_score(actual_nodes: Iterable[str], expected_nodes: Iterable[str]) -> float:
    """Order-sensitive trajectory coverage without exposing model reasoning."""

    actual = list(actual_nodes)
    expected = list(expected_nodes)
    if not expected:
        return 1.0
    cursor = 0
    matched = 0
    for node in actual:
        if cursor < len(expected) and node == expected[cursor]:
            matched += 1
            cursor += 1
    return matched / len(expected)
