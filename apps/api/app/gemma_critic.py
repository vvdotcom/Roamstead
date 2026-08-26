"""Gemma 4 multimodal second opinion for real listing evidence.

The critic receives only the deterministic evidence packet, public Gemini
analysis, and locally cached exact-listing photos. It cannot change ranking or
profile state and its typed output remains an evidence aid, not a property fact.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from PIL import Image
from pydantic import BaseModel, Field

from .models import PropertyVisualAudit, VisualEvidenceAudit, VisualImageAssessment


_MODULE_PATH = Path(__file__).resolve()
PROJECT_ROOT = _MODULE_PATH.parents[3] if len(_MODULE_PATH.parents) > 3 else Path.cwd()
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class VisualImageInput:
    listing_id: str
    image_index: int
    image_url: str
    path: Path


class _RawImageAssessment(BaseModel):
    image_index: int = Field(ge=0)
    classification: Literal["INTERIOR", "EXTERIOR", "FLOOR_PLAN", "DOCUMENT", "UNKNOWN"]
    observations: list[str] = Field(default_factory=list, max_length=4)
    warnings: list[str] = Field(default_factory=list, max_length=4)
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"


class _RawPropertyAudit(BaseModel):
    listing_id: str
    verdict: Literal["SUPPORTED", "CHALLENGE", "INSUFFICIENT"]
    images: list[_RawImageAssessment] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list, max_length=5)
    missing_evidence: list[str] = Field(default_factory=list, max_length=5)
    suggested_questions: list[str] = Field(default_factory=list, max_length=5)


class _RawVisualAudit(BaseModel):
    verdict: Literal["SUPPORTED", "CHALLENGE"]
    summary: str = Field(min_length=1, max_length=420)
    properties: list[_RawPropertyAudit] = Field(default_factory=list)
    challenged_claims: list[str] = Field(default_factory=list, max_length=8)


def gemma_model() -> str:
    return os.getenv("ROAMSTEAD_GEMMA_MODEL", "gemma-4-26b-a4b-it")


def gemma_critic_enabled() -> bool:
    if os.getenv("ENABLE_GEMMA_CRITIC", "1") == "0":
        return False
    return bool(os.getenv("GEMMA_CRITIC_URL") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def gemma_provider() -> str:
    if os.getenv("GEMMA_CRITIC_URL"):
        return "CLOUD_RUN_VLLM"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "GEMINI_API"
    return "DISABLED"


def maximum_photos_per_listing() -> int:
    return max(1, min(2, int(os.getenv("GEMMA_PHOTOS_PER_LISTING", "1"))))


def _prompt(evidence_packet: list[dict], specialist_outputs: dict[str, str], images: list[VisualImageInput]) -> str:
    image_manifest = [{"listing_id": item.listing_id, "image_index": item.image_index} for item in images]
    payload = json.dumps(
        {
            "deterministic_evidence": evidence_packet,
            "public_specialist_outputs": specialist_outputs,
            "attached_image_manifest": image_manifest,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "You are VisualEvidenceCritic, an independent Gemma 4 multimodal specialist. Audit the attached exact-listing "
        "photos and whether the public Gemini analysis stays within the deterministic packet. Classify each image as "
        "INTERIOR, EXTERIOR, FLOOR_PLAN, DOCUMENT, or UNKNOWN. Report only directly observable visual features. Never "
        "infer availability, condition not visible, ownership, legal eligibility, neighborhood quality, room identity, "
        "photo recency, or a feature hidden outside the frame. A photo cannot confirm a listing's price or specification. "
        "Deterministic source facts do not become unsupported merely because a photo cannot prove them: record that limit "
        "as missing_evidence and use INSUFFICIENT at the property level. Use overall CHALLENGE only when the analyst adds a "
        "claim absent from the deterministic packet, contradicts the packet, or explicitly says a photo proves a feature "
        "the image does not show. Do not challenge an exact source-reported price, bed/bath count, or area solely because "
        "the gallery is visually insufficient. Use INSUFFICIENT per property when photos are missing, documents, floor "
        "plans, or otherwise inadequate to visually assess the home. Suggested questions must be practical requests "
        "for a live tour or additional exact-property photos. Return JSON only, matching the supplied schema. Input: "
        + payload
    )


def _prepared_jpeg(path: Path) -> bytes:
    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail((1280, 1280))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=82, optimize=True)
        return output.getvalue()


def _extract_json(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("Gemma visual critic returned no JSON object")
    return json.loads(match.group(0))


def _normalize(
    raw: str,
    provider: Literal["GEMINI_API", "CLOUD_RUN_VLLM"],
    images: list[VisualImageInput],
) -> VisualEvidenceAudit:
    payload = _extract_json(raw)
    payload["summary"] = re.sub(r"\s+", " ", str(payload.get("summary") or "")).strip()[:420]
    parsed = _RawVisualAudit.model_validate(payload)
    expected_listing_ids = list(dict.fromkeys(item.listing_id for item in images))
    raw_by_listing = {item.listing_id: item for item in parsed.properties}
    properties: list[PropertyVisualAudit] = []

    for listing_id in expected_listing_ids:
        raw_property = raw_by_listing.get(listing_id)
        expected_images = [item for item in images if item.listing_id == listing_id]
        raw_images = {item.image_index: item for item in raw_property.images} if raw_property else {}
        normalized_images: list[VisualImageAssessment] = []
        for expected in expected_images:
            result = raw_images.get(expected.image_index)
            if result:
                normalized_images.append(VisualImageAssessment(image_url=expected.image_url, **result.model_dump()))
            else:
                normalized_images.append(
                    VisualImageAssessment(
                        image_index=expected.image_index,
                        image_url=expected.image_url,
                        classification="UNKNOWN",
                        warnings=["Gemma did not return an assessment for this attached image."],
                        confidence="LOW",
                    )
                )
        if raw_property:
            properties.append(
                PropertyVisualAudit(
                    listing_id=listing_id,
                    verdict=raw_property.verdict,
                    images=normalized_images,
                    unsupported_claims=raw_property.unsupported_claims,
                    missing_evidence=raw_property.missing_evidence,
                    suggested_questions=raw_property.suggested_questions,
                )
            )
        else:
            properties.append(
                PropertyVisualAudit(
                    listing_id=listing_id,
                    verdict="INSUFFICIENT",
                    images=normalized_images,
                    missing_evidence=["Gemma did not return a property-level visual audit."],
                    suggested_questions=["Request current exact-property photos and a live video tour."],
                )
            )

    challenged = list(parsed.challenged_claims)
    for item in properties:
        challenged.extend(item.unsupported_claims)
    verdict = "CHALLENGE" if challenged else parsed.verdict
    return VisualEvidenceAudit(
        verdict=verdict,
        summary=re.sub(r"\s+", " ", parsed.summary).strip(),
        properties=properties,
        challenged_claims=list(dict.fromkeys(challenged))[:8],
        model=gemma_model(),
        provider=provider,
        analyzed_photo_count=len(images),
    )


async def _cloud_run_token(audience: str) -> str:
    def fetch() -> str:
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import fetch_id_token

        return fetch_id_token(Request(), audience)

    return await asyncio.to_thread(fetch)


async def _audit_with_cloud_run(prompt: str, images: list[VisualImageInput]) -> VisualEvidenceAudit:
    base_url = os.environ["GEMMA_CRITIC_URL"].rstrip("/")
    endpoint = base_url if base_url.endswith("/v1/chat/completions") else f"{base_url}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if os.getenv("GEMMA_CRITIC_AUTH", "iam").lower() != "none":
        audience = os.getenv("GEMMA_CRITIC_AUDIENCE", base_url)
        headers["Authorization"] = f"Bearer {await _cloud_run_token(audience)}"
    content: list[dict] = [{"type": "text", "text": prompt}]
    for item in images:
        encoded = base64.b64encode(_prepared_jpeg(item.path)).decode("ascii")
        content.extend(
            [
                {"type": "text", "text": f"listing_id={item.listing_id}; image_index={item.image_index}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
            ]
        )
    timeout = float(os.getenv("GEMMA_CRITIC_TIMEOUT_SECONDS", "45"))
    body = {
        "model": gemma_model(),
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 1800,
        "chat_template_kwargs": {"enable_thinking": True},
        "skip_special_tokens": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint, headers=headers, json=body)
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
    return _normalize(raw, "CLOUD_RUN_VLLM", images)


async def _audit_with_gemini_api(prompt: str, images: list[VisualImageInput]) -> VisualEvidenceAudit:
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    def generate() -> str:
        client = genai.Client(api_key=api_key)
        parts = [types.Part.from_text(text=prompt)]
        for item in images:
            parts.append(types.Part.from_text(text=f"listing_id={item.listing_id}; image_index={item.image_index}"))
            parts.append(types.Part.from_bytes(data=_prepared_jpeg(item.path), mime_type="image/jpeg"))
        response = client.models.generate_content(
            model=gemma_model(),
            contents=types.Content(role="user", parts=parts),
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=1800,
                response_mime_type="application/json",
                response_json_schema=_RawVisualAudit.model_json_schema(),
            ),
        )
        return response.text or ""

    timeout = float(os.getenv("GEMMA_CRITIC_TIMEOUT_SECONDS", "45"))
    raw = await asyncio.wait_for(asyncio.to_thread(generate), timeout=timeout)
    return _normalize(raw, "GEMINI_API", images)


async def audit_visual_evidence(
    evidence_packet: list[dict],
    specialist_outputs: dict[str, str],
    images: list[VisualImageInput],
) -> VisualEvidenceAudit | None:
    if not gemma_critic_enabled():
        return None
    if not images:
        raise ValueError("No locally cached real listing photos are available for Gemma")
    prompt = _prompt(evidence_packet, specialist_outputs, images)
    if os.getenv("GEMMA_CRITIC_URL"):
        return await _audit_with_cloud_run(prompt, images)
    return await _audit_with_gemini_api(prompt, images)
