from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.evaluation_artifacts import curated_failed_run_ids, persist_evaluation_artifact


ROOT = Path(__file__).resolve().parents[1]
EVALSET = ROOT / "evaluation_data" / "preference_interpreter.evalset.json"
EVAL_CONFIG = ROOT / "evaluation_data" / "test_config.json"
AGENT_SOURCE = ROOT / "eval_agents" / "preference_interpreter"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Produce an isolated PreferenceInterpreter prompt candidate with ADK optimize."
    )
    parser.add_argument("--optimizer-model", default="gemini-3.5-flash")
    parser.add_argument("--max-metric-calls", type=int, default=40)
    args = parser.parse_args()

    eval_payload = json.loads(EVALSET.read_text(encoding="utf-8"))
    eval_set_id = eval_payload["eval_set_id"]
    dev_ids = [item["eval_id"] for item in eval_payload["eval_cases"] if item["eval_id"].startswith("dev_")]
    validation_ids = [
        item["eval_id"] for item in eval_payload["eval_cases"] if item["eval_id"].startswith("validation_")
    ]
    if len(dev_ids) != 12 or len(validation_ids) != 8:
        raise SystemExit("Optimization requires exactly 12 development and 8 held-out validation cases")

    with tempfile.TemporaryDirectory(prefix="roamstead-adk-optimize-") as temporary:
        workspace = Path(temporary)
        agent_dir = workspace / "preference_interpreter"
        shutil.copytree(AGENT_SOURCE, agent_dir)
        shutil.copy2(EVALSET, agent_dir / f"{eval_set_id}.evalset.json")
        sampler = {
            "eval_config": json.loads(EVAL_CONFIG.read_text(encoding="utf-8")),
            "app_name": "preference_interpreter",
            "train_eval_set": eval_set_id,
            "train_eval_case_ids": dev_ids,
            "validation_eval_set": eval_set_id,
            "validation_eval_case_ids": validation_ids,
        }
        optimizer = {
            "optimizer_model": args.optimizer_model,
            "max_metric_calls": max(1, min(args.max_metric_calls, 100)),
            "reflection_minibatch_size": 3,
            "run_dir": str(workspace / "optimizer-output"),
        }
        sampler_path = workspace / "sampler.json"
        optimizer_path = workspace / "optimizer.json"
        sampler_path.write_text(json.dumps(sampler), encoding="utf-8")
        optimizer_path.write_text(json.dumps(optimizer), encoding="utf-8")
        completed = subprocess.run(
            [
                "adk",
                "optimize",
                str(agent_dir),
                f"--sampler_config_file_path={sampler_path}",
                f"--optimizer_config_file_path={optimizer_path}",
            ],
            cwd=workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"ADK optimization failed: {(completed.stdout + completed.stderr)[-2000:]}")
        match = re.search(
            r"Optimized root agent instructions:\s*-+\s*(.*?)\s*=+",
            completed.stdout,
            flags=re.DOTALL,
        )
        if not match:
            raise RuntimeError("ADK optimization did not return a parseable prompt candidate")
        instruction = match.group(1).strip()

    digest = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    candidate_version = f"preference-interpreter-candidate-{digest[:12]}"
    artifact_uri = persist_evaluation_artifact(
        "prompt-candidates/private",
        candidate_version,
        {
            "candidate_prompt_version": candidate_version,
            "candidate_instruction": instruction,
            "instruction_sha256": digest,
            "development_case_count": len(dev_ids),
            "validation_case_count": len(validation_ids),
            "curated_failed_run_ids": curated_failed_run_ids(),
            "status": "AWAITING_HELD_OUT_EVALUATION",
            "activation_allowed": False,
        },
        contains_prompts=True,
    )
    if not artifact_uri:
        raise SystemExit("ROAMSTEAD_EVALUATION_BUCKET is required; prompt candidates must remain private")
    print(f"Candidate created: {candidate_version}")
    print(f"Private candidate: {artifact_uri}")
    print("It is not active. Evaluate it, persist the candidate report, then use propose_prompt_revision.py.")


if __name__ == "__main__":
    main()
