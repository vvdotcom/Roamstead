import json
from pathlib import Path

from app.evaluation import create_evaluation_report, propose_prompt_revision, trajectory_score
from app.observability import adk_analytics_plugins


EVAL_PATH = Path(__file__).parents[1] / "evaluation_data" / "preference_interpreter.evalset.json"


def _gates(value: bool = True) -> dict[str, bool]:
    return {
        "approval_required": value,
        "hard_filters_preserved": value,
        "profile_memory_isolated": value,
        "real_data_only": value,
        "correction_limit": value,
        "no_vector_exposure": value,
    }


def test_formal_evalset_contains_twelve_development_and_eight_validation_cases():
    payload = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    ids = [item["eval_id"] for item in payload["eval_cases"]]
    assert len(ids) == 20
    assert len([item for item in ids if item.startswith("dev_")]) == 12
    assert len([item for item in ids if item.startswith("validation_")]) == 8
    assert all(case["session_input"]["state"]["real_snapshot"] for case in payload["eval_cases"])
    assert all(case["session_input"]["state"]["approval_required"] for case in payload["eval_cases"])


def test_evaluation_badge_requires_every_hard_gate_and_both_metric_thresholds():
    passing = create_evaluation_report(response_score=0.88, trajectory_score=0.95, hard_gate_results=_gates())
    assert passing.passed
    failed_gates = _gates()
    failed_gates["real_data_only"] = False
    failed = create_evaluation_report(response_score=1.0, trajectory_score=1.0, hard_gate_results=failed_gates)
    assert not failed.passed
    assert not failed.hard_gates_passed


def test_prompt_candidate_never_activates_without_improvement_and_no_regression():
    baseline = create_evaluation_report(response_score=0.86, trajectory_score=0.91, hard_gate_results=_gates())
    candidate = create_evaluation_report(
        response_score=0.94,
        trajectory_score=0.96,
        hard_gate_results=_gates(),
        prompt_version="preference-interpreter-v2-candidate",
        source="ADK_EVAL",
    )
    proposal = propose_prompt_revision(baseline, candidate)
    assert proposal.activation_allowed
    assert proposal.status == "PROPOSED"

    regressed = create_evaluation_report(
        response_score=0.99,
        trajectory_score=0.88,
        hard_gate_results=_gates(),
        prompt_version="preference-interpreter-v3-candidate",
        source="ADK_EVAL",
    )
    assert not propose_prompt_revision(baseline, regressed).activation_allowed


def test_trajectory_score_is_order_sensitive_and_does_not_require_private_reasoning():
    expected = ["LockDecisionInputs", "RecalculateFitScores", "ListingAnalyst", "CriticJoin", "EvidenceVerifier"]
    assert trajectory_score(expected, expected) == 1.0
    assert trajectory_score(reversed(expected), expected) < 0.5


def test_bigquery_plugin_physically_excludes_private_content(monkeypatch):
    monkeypatch.setenv("ENABLE_BIGQUERY_AGENT_ANALYTICS", "1")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    plugins = adk_analytics_plugins()
    assert len(plugins) == 1
    assert set(plugins[0].config.payload_column_denylist) == {"content", "content_parts"}
    assert plugins[0].config.log_multi_modal_content is False
    assert plugins[0].config.log_session_metadata is False
