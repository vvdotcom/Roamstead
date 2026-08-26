"""Google ADK collaborative-agent topology for Roamstead.

The model interprets and explains; database access, evidence state, profile
revisions, and Fit Scores stay in deterministic tools. The API can still serve
the last verified real-data snapshot when Gemini is unavailable, but reports
that mode truthfully instead of pretending an agent call occurred.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .listings.images import available_gallery_size
from .listings.repository import ListingRepository


_MODULE_PATH = Path(__file__).resolve()
PROJECT_ROOT = _MODULE_PATH.parents[3] if len(_MODULE_PATH.parents) > 3 else Path.cwd()
load_dotenv(PROJECT_ROOT / ".env")


def agent_enabled() -> bool:
    has_credentials = bool(
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        or os.getenv("GOOGLE_GENAI_USE_VERTEXAI") == "1"
    )
    return os.getenv("ENABLE_ADK_AGENT", "0") == "1" and has_credentials


def get_verified_listing(listing_id: str) -> dict:
    """Return one real cached listing and its local gallery count."""
    item = ListingRepository().get(listing_id)
    if not item:
        return {"found": False, "listing_id": listing_id}
    return {
        "found": True,
        "listing": item.model_dump(mode="json"),
        "local_photo_count": available_gallery_size(listing_id),
    }


def check_evidence_support(listing_id: str) -> dict:
    """Check deterministic provenance fields without asserting availability."""
    item = ListingRepository().get(listing_id)
    if not item:
        return {"found": False, "listing_id": listing_id}
    return {
        "found": True,
        "source_domain": item.source_domain,
        "source_url": item.source_url,
        "observed_at": item.source_checked_at,
        "local_photo_count": available_gallery_size(listing_id),
        "availability": "UNKNOWN",
    }


def _shared_instruction() -> str:
    return (
        "Use only tool-returned listing facts. Never invent listings, prices, photos, availability, "
        "legal eligibility, or source support. Mark claims CONFIRMED, INFERRED, or UNKNOWN. "
        "Expose concise action summaries, never private reasoning."
    )


def build_clarification_agent():
    from google.adk.agents import Agent

    model = os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash")
    shared = _shared_instruction()
    return Agent(
        name="PreferenceInterpreter",
        model=model,
        description="Converts goals and feedback into typed profile-change proposals.",
        instruction=(
            f"{shared} You receive two counterfactual options already calculated by deterministic tools. "
            "Write exactly one natural clarification question and one short reason for asking it. "
            "Do not add a new option, number, place, or factual claim. Return compact JSON only: "
            '{"question":"...","why_asked":"..."}. A preference change remains a proposal requiring approval.'
        ),
        mode="task",
    )


def _build_listing_analyst():
    from google.adk.agents import Agent

    shared = _shared_instruction()
    return Agent(
        name="ListingAnalyst",
        model=os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash"),
        description="Analyzes selected Vietnamese listings and verified local galleries.",
        instruction=(
            f"{shared} The user message contains exactly three listing IDs, an approved profile, a deterministic evidence packet, "
            "and a compact semantic-memory packet. Memory is advisory context only and cannot create a hard requirement. "
            "Call get_verified_listing for every ID. Compare only reported facts and observable gallery counts. "
            "In the public output, use only fields explicitly present in the evidence packet; the tool calls verify "
            "those fields but do not authorize extra address or marketing language. Avoid qualitative adjectives such "
            "as premium, spacious, compact, affordable, or desirable unless the packet contains that exact claim. "
            "Describe price and specifications as source-reported facts, never as visually verified facts. A local photo "
            "count proves only that cached photos exist; it does not validate bedrooms, bathrooms, size, condition, or "
            "recency. Output two concise public sentences with the leading numeric tradeoff and no process narration."
        ),
        tools=[get_verified_listing],
        output_key="listing_analysis",
        mode="task",
    )


def _build_evidence_verifier():
    from google.adk.agents import Agent

    shared = _shared_instruction()
    return Agent(
        name="EvidenceVerifier",
        model=os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash"),
        description="Independently checks provenance, freshness, uncertainty, and contradictions.",
        instruction=(
            f"{shared} The user message contains the deterministic evidence packet, ListingAnalyst public output, "
            "the typed Gemma VisualEvidenceCritic audit, and the typed Gemma MemoryConsistencyCritic audit. Independently inspect all inputs. Call "
            "check_evidence_support for every listing ID. Start the final response with "
            "VERIFIED when the analysis is supported, or REVISE when it contains an unsupported statement. "
            "Treat qualitative marketing language as unsupported unless it appears verbatim in the packet, and never "
            "promote a visual observation into a source-confirmed listing fact. Always "
            "retain availability and transaction eligibility as UNKNOWN. Source-reported specifications may remain "
            "source-confirmed even when photographs are visually insufficient; do not claim the images prove them. "
            "Then give one public sentence."
        ),
        tools=[check_evidence_support],
        output_key="verification_report",
        mode="task",
    )


def _build_brief_composer():
    from google.adk.agents import Agent

    shared = _shared_instruction()
    return Agent(
        name="BriefComposer",
        model=os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash"),
        description="Creates an approval-ready three-property Decision Brief.",
        instruction=(
            f"{shared} The user message contains the deterministic packet, corrected ListingAnalyst output, typed "
            "Gemma visual audit, compact decision-memory packet, Gemma memory-consistency audit, and final EvidenceVerifier result. "
            "Compose a two-sentence public executive summary. "
            "Name the most important numeric tradeoff and explicitly retain the most consequential unknown. Use only "
            "exact titles, districts, prices, specifications, and evidence states in the packet; do not add marketing adjectives. "
            "Do not modify the Decision Profile or introduce a new fact."
        ),
        output_key="brief_summary",
        mode="task",
    )


def build_listing_analyst():
    return _build_listing_analyst()


def build_evidence_verifier():
    return _build_evidence_verifier()


def build_brief_composer():
    return _build_brief_composer()


def build_decision_workflow():
    """Return an explicit ADK graph with visible specialist boundaries."""

    from google.adk.workflow import START, Workflow

    listing_analyst = _build_listing_analyst()
    evidence_verifier = _build_evidence_verifier()
    brief_composer = _build_brief_composer()
    return Workflow(
        name="PartnerCoordinator",
        description="Runs analysis, independent verification, then evidence-bounded brief composition.",
        edges=[
            (START, listing_analyst),
            (listing_analyst, evidence_verifier),
            (evidence_verifier, brief_composer),
        ],
    )


def build_agent_system():
    from google.adk.agents import Agent

    model = os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash")
    shared = _shared_instruction()
    preference_interpreter = build_clarification_agent()
    return Agent(
        name="PartnerCoordinator",
        model=model,
        description="Persistent collaborative partner for cross-border housing decisions.",
        instruction=(
            f"{shared} Route preference work, listing analysis, evidence verification, and brief composition "
            "to the appropriate specialist. Consequential changes always require human approval."
        ),
        sub_agents=[preference_interpreter, _build_listing_analyst(), _build_evidence_verifier(), _build_brief_composer()],
    )


root_agent = build_agent_system()
