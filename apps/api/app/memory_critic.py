"""Gemma 4 31B audit of user-memory consistency.

This specialist may challenge public analysis, but it cannot mutate the profile,
ranking, hard filters, prices, or evidence labels.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from time import monotonic
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from .models import MemoryConsistencyAudit, MemoryContextPacket


class _RawMemoryAudit(BaseModel):
    verdict: Literal["CONSISTENT", "CHALLENGE", "INSUFFICIENT"]
    summary: str = Field(min_length=1, max_length=500)
    relevant_memory_ids: list[str] = Field(default_factory=list, max_length=8)
    conflicting_preferences: list[str] = Field(default_factory=list, max_length=6)
    superseded_preferences: list[str] = Field(default_factory=list, max_length=6)
    unsupported_user_assumptions: list[str] = Field(default_factory=list, max_length=6)
    omitted_tradeoffs: list[str] = Field(default_factory=list, max_length=6)
    suggested_questions: list[str] = Field(default_factory=list, max_length=5)


def memory_critic_model() -> str:
    return os.getenv("ROAMSTEAD_MEMORY_CRITIC_MODEL", "gemma-4-31b-it")


def memory_critic_enabled() -> bool:
    enabled = os.getenv("ENABLE_MEMORY_CRITIC", "1").strip().casefold() not in {"0", "false", "no", "off"}
    return enabled and bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _extract_json(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("Gemma memory critic returned no JSON object")
    return json.loads(match.group(0))


async def audit_memory_consistency(
    *,
    profile: dict,
    memory_context: MemoryContextPacket,
    evidence_packet: list[dict],
    listing_analysis: str,
    visual_audit: dict | None,
) -> MemoryConsistencyAudit | None:
    if not memory_critic_enabled():
        return None
    allowed_ids = {item.memory_id for item in memory_context.matches}
    payload = {
        "approved_profile": profile,
        "retrieved_decision_memory": memory_context.model_dump(mode="json"),
        "deterministic_listing_evidence": evidence_packet,
        "public_listing_analysis": listing_analysis,
        "visual_evidence_audit": visual_audit,
    }
    prompt = (
        "You are MemoryConsistencyCritic, an independent Gemma 4 specialist. Audit whether the public listing analysis "
        "faithfully reflects the approved profile and the compact retrieved decision memory. Challenge unsupported claims "
        "about the user, ignored conflicts, superseded preferences, or an important tradeoff omitted from the comparison. "
        "Memory records are context, never hard requirements. A rejected proposal means the user declined that mutation. "
        "Do not alter or recompute hard filters, Fit Scores, prices, profile weights, or evidence statuses. Cite only memory "
        "IDs present in the input. Use INSUFFICIENT if no useful memory was retrieved. Return JSON only. Input: "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )

    def _call() -> str:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        response = client.models.generate_content(
            model=memory_critic_model(),
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=1600,
                response_mime_type="application/json",
                response_json_schema=_RawMemoryAudit.model_json_schema(),
            ),
        )
        return response.text or ""

    started = monotonic()
    timeout = float(os.getenv("MEMORY_CRITIC_TIMEOUT_SECONDS", "45"))
    raw = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
    payload = _extract_json(raw)
    payload["summary"] = re.sub(r"\s+", " ", str(payload.get("summary") or "")).strip()[:500]
    parsed = _RawMemoryAudit.model_validate(payload)
    relevant_ids = list(dict.fromkeys(item for item in parsed.relevant_memory_ids if item in allowed_ids))[:8]
    return MemoryConsistencyAudit(
        **parsed.model_dump(exclude={"relevant_memory_ids"}),
        relevant_memory_ids=relevant_ids,
        model=memory_critic_model(),
        duration_ms=round((monotonic() - started) * 1000),
    )
