from __future__ import annotations

import hashlib
import json
import os
from typing import Any


def persist_evaluation_artifact(
    prefix: str,
    artifact_id: str,
    payload: dict[str, Any],
    *,
    contains_prompts: bool = False,
) -> str | None:
    """Write a private, integrity-attested evaluation artifact to Cloud Storage."""

    bucket_name = os.getenv("ROAMSTEAD_EVALUATION_BUCKET")
    if not bucket_name:
        return None
    from google.cloud import storage

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    object_name = f"{prefix.strip('/')}/{artifact_id}.json"
    blob = storage.Client(project=os.getenv("GCP_PROJECT_ID") or None).bucket(bucket_name).blob(object_name)
    if blob.exists():
        blob.reload()
        if (blob.metadata or {}).get("sha256") != digest:
            raise RuntimeError(f"Evaluation artifact collision for {object_name}")
        return f"gs://{bucket_name}/{object_name}#sha256={digest}"
    blob.metadata = {
        "sha256": digest,
        "schema": "roamstead-evaluation-artifact-v1",
        "contains_prompts": str(contains_prompts).lower(),
        "contains_personal_data": "false",
    }
    blob.upload_from_string(encoded, content_type="application/json", if_generation_match=0)
    return f"gs://{bucket_name}/{object_name}#sha256={digest}"


def curated_failed_run_ids(limit: int = 50) -> list[str]:
    """Read operator-curated failed run identifiers without event content."""

    project_id = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("ROAMSTEAD_AGENT_ANALYTICS_DATASET")
    if not project_id or not dataset:
        return []
    from google.cloud import bigquery

    query = f"""
        SELECT run_id
        FROM `{project_id}.{dataset}.evaluation_candidates`
        WHERE status = 'CURATED'
        ORDER BY curated_at DESC
        LIMIT @limit
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", max(1, min(limit, 200)))]
    )
    rows = bigquery.Client(project=project_id).query(query, job_config=config).result()
    return [str(row.run_id) for row in rows if row.run_id]
