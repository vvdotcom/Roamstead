from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Any


logger = logging.getLogger(__name__)
_trace_lock = Lock()
_trace_configured = False


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().casefold() in {"1", "true", "yes", "on"}


def configure_cloud_trace() -> bool:
    """Configure one process-wide Cloud Trace exporter when explicitly enabled."""

    global _trace_configured
    if not _enabled("ENABLE_CLOUD_TRACE"):
        return False
    with _trace_lock:
        if _trace_configured:
            return True
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = trace.get_tracer_provider()
            if not isinstance(provider, TracerProvider):
                provider = TracerProvider()
                trace.set_tracer_provider(provider)
            provider.add_span_processor(
                BatchSpanProcessor(
                    CloudTraceSpanExporter(project_id=os.getenv("GCP_PROJECT_ID") or None)
                )
            )
            _trace_configured = True
            return True
        except Exception:
            logger.exception("Cloud Trace setup failed; the agent run will continue without trace export")
            return False


def adk_analytics_plugins() -> list[Any]:
    """Return privacy-bounded ADK plugins for production workflow runs.

    Model prompts, responses, images, vectors, profile text, and tool payloads are
    physically projected out of the BigQuery table. The retained envelope is
    limited to event identity, node/model metadata, timing, and trace correlation.
    """

    trace_enabled = configure_cloud_trace()
    if not _enabled("ENABLE_BIGQUERY_AGENT_ANALYTICS"):
        return []
    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        logger.warning("BigQuery agent analytics enabled without GCP_PROJECT_ID; skipping plugin")
        return []
    try:
        from google.adk.plugins.bigquery_agent_analytics_plugin import (
            BigQueryAgentAnalyticsPlugin,
            BigQueryLoggerConfig,
        )

        config = BigQueryLoggerConfig(
            table_id=os.getenv("ROAMSTEAD_AGENT_ANALYTICS_TABLE", "agent_events"),
            log_multi_modal_content=False,
            log_session_metadata=False,
            max_content_length=1,
            payload_column_denylist=["content", "content_parts"],
            custom_metadata_allowlist=[],
            enable_otel_correlation=trace_enabled,
            custom_tags={
                "application": "roamstead",
                "workflow_version": os.getenv(
                    "ROAMSTEAD_WORKFLOW_VERSION", "partner-coordinator-v2"
                ),
                "prompt_version": os.getenv(
                    "ROAMSTEAD_PROMPT_VERSION", "preference-interpreter-v1"
                ),
                "redaction_policy": "metadata-only-v1",
            },
            flush_on_run_end=True,
        )
        return [
            BigQueryAgentAnalyticsPlugin(
                project_id=project_id,
                dataset_id=os.getenv(
                    "ROAMSTEAD_AGENT_ANALYTICS_DATASET", "roamstead_agent_analytics"
                ),
                config=config,
                location=os.getenv("ROAMSTEAD_AGENT_ANALYTICS_LOCATION", "US"),
            )
        ]
    except Exception:
        logger.exception("BigQuery agent analytics setup failed; workflow execution remains available")
        return []
