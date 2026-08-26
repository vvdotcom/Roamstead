from __future__ import annotations

import asyncio
import hashlib
import math
import os
from datetime import datetime, timezone

from google import genai
from google.genai import types

from .models import (
    MemoryContextMatch,
    MemoryContextPacket,
    SemanticMemoryItem,
    SemanticMemoryPublic,
)


def _enabled(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().casefold() not in {"0", "false", "no", "off"}


EMBEDDING_MODEL = os.getenv("ROAMSTEAD_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIMENSION = int(os.getenv("ROAMSTEAD_EMBEDDING_DIMENSION", "768"))
MEMORY_TOP_K = min(5, max(1, int(os.getenv("ROAMSTEAD_MEMORY_TOP_K", "5"))))
MEMORY_MAX_CHARS = min(6000, max(500, int(os.getenv("ROAMSTEAD_MEMORY_MAX_CHARS", "6000"))))
MEMORY_MAX_DISTANCE = float(os.getenv("ROAMSTEAD_MEMORY_MAX_COSINE_DISTANCE", "0.30"))
EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("ROAMSTEAD_EMBEDDING_TIMEOUT_SECONDS", "20"))


def semantic_memory_enabled() -> bool:
    return _enabled("ENABLE_SEMANTIC_MEMORY") and bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def memory_id(source_event_id: str) -> str:
    return f"memory-{hashlib.sha256(source_event_id.encode('utf-8')).hexdigest()[:24]}"


def public_memory(item: SemanticMemoryItem) -> SemanticMemoryPublic:
    return SemanticMemoryPublic(
        id=item.id,
        source_event_id=item.source_event_id,
        kind=item.kind,
        preference_key=item.preference_key,
        source_text=item.source_text,
        target_id=item.target_id,
        target_name=item.target_name,
        city=item.city,
        transaction_mode=item.transaction_mode,
        decision_status=item.decision_status,
        embedding_status=item.embedding_status,
        embedding_model=item.embedding_model,
        created_at=item.created_at,
    )


def cosine_distance(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Embedding dimensions do not match")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Embedding vector cannot have zero magnitude")
    return max(0.0, min(2.0, 1.0 - dot / (left_norm * right_norm)))


async def embed_text(text: str, task_type: str) -> list[float]:
    if not semantic_memory_enabled():
        raise RuntimeError("SEMANTIC_MEMORY_DISABLED")

    def _call() -> list[float]:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBEDDING_DIMENSION,
            ),
        )
        values = list(response.embeddings[0].values or []) if response.embeddings else []
        if len(values) != EMBEDDING_DIMENSION or not all(math.isfinite(float(value)) for value in values):
            raise ValueError("INVALID_EMBEDDING_VECTOR")
        return [float(value) for value in values]

    return await asyncio.wait_for(asyncio.to_thread(_call), timeout=EMBEDDING_TIMEOUT_SECONDS)


async def persist_memory(repository, item: SemanticMemoryItem) -> SemanticMemoryItem:
    """Idempotently persist first, then enrich with an embedding if needed."""
    existing = repository.get_semantic_memory(item.id)
    if existing and existing.embedding_status == "READY" and existing.embedding_model == EMBEDDING_MODEL:
        return existing
    repository.save_semantic_memory(item)
    try:
        item.embedding = await embed_text(item.source_text, "RETRIEVAL_DOCUMENT")
        item.embedding_status = "READY"
        item.embedding_model = EMBEDDING_MODEL
        item.embedding_dimension = EMBEDDING_DIMENSION
        item.error_code = None
    except Exception as exc:
        item.embedding = []
        item.embedding_status = "PENDING_EMBEDDING"
        item.error_code = type(exc).__name__.upper()
    item.updated_at = datetime.now(timezone.utc).isoformat()
    repository.save_semantic_memory(item)
    return item


async def retrieve_memory(
    repository,
    profile_id: str,
    query: str,
    preference_key: str | None = None,
    exclude_ids: set[str] | None = None,
) -> MemoryContextPacket:
    packet = MemoryContextPacket(
        query=query[:1000],
        model=EMBEDDING_MODEL,
        dimension=EMBEDDING_DIMENSION,
    )
    try:
        stale = [
            item
            for item in repository.list_semantic_memory(profile_id)
            if item.embedding_status == "PENDING_EMBEDDING"
            or item.embedding_model != EMBEDDING_MODEL
            or item.embedding_dimension != EMBEDDING_DIMENSION
        ][:5]
        for item in stale:
            await persist_memory(repository, item)
        query_vector = await embed_text(query, "RETRIEVAL_QUERY")
        candidates = repository.vector_search_semantic_memory(profile_id, query_vector, limit=20)
    except Exception as exc:
        packet.error_code = type(exc).__name__.upper()
        return packet

    excluded_ids = exclude_ids or set()
    evaluated: list[tuple[SemanticMemoryItem, float]] = []
    for item, cloud_distance in candidates:
        if item.id in excluded_ids or item.embedding_status != "READY":
            continue
        if preference_key and item.preference_key != preference_key:
            continue
        try:
            distance = cloud_distance if cloud_distance is not None else cosine_distance(query_vector, item.embedding)
        except ValueError:
            continue
        evaluated.append((item, distance))
    evaluated.sort(key=lambda pair: (pair[1], pair[0].created_at))
    packet.considered_count = len(evaluated)
    used_characters = 0
    for item, distance in evaluated:
        if distance > MEMORY_MAX_DISTANCE or len(packet.matches) >= MEMORY_TOP_K:
            continue
        available = MEMORY_MAX_CHARS - used_characters
        if available <= 0:
            break
        text = item.source_text[:available]
        if not text:
            continue
        packet.matches.append(
            MemoryContextMatch(
                memory_id=item.id,
                kind=item.kind,
                preference_key=item.preference_key,
                text=text,
                target_name=item.target_name,
                city=item.city,
                decision_status=item.decision_status,
                cosine_distance=round(distance, 4),
                created_at=item.created_at,
            )
        )
        used_characters += len(text)
    packet.selected_count = len(packet.matches)
    packet.excluded_count = max(0, packet.considered_count - packet.selected_count)
    packet.context_characters = used_characters
    packet.status = "READY"
    return packet


def make_memory(
    *,
    profile_id: str,
    source_event_id: str,
    kind: str,
    source_text: str,
    preference_key: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    city: str | None = "Ho Chi Minh City",
    transaction_mode: str | None = None,
    decision_status: str = "ACTIVE",
) -> SemanticMemoryItem:
    return SemanticMemoryItem(
        id=memory_id(source_event_id),
        profile_id=profile_id,
        source_event_id=source_event_id,
        kind=kind,
        preference_key=preference_key,
        source_text=source_text.strip()[:6000],
        target_id=target_id,
        target_name=target_name,
        city=city,
        transaction_mode=transaction_mode,
        decision_status=decision_status,
        embedding_model=EMBEDDING_MODEL,
        embedding_dimension=EMBEDDING_DIMENSION,
    )
