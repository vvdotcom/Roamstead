from __future__ import annotations

import os
from copy import deepcopy

from .cloud import get_document


VIDEO_MODEL = os.getenv("ROAMSTEAD_CITY_VIDEO_MODEL", "veo-3.1-lite-generate-preview")
NARRATION_MODEL = os.getenv("ROAMSTEAD_CITY_NARRATION_MODEL", "gemini-3.1-flash-tts-preview")
DISCLAIMER = "Generated city orientation — not a property photograph or property evidence."

CITY_ORIENTATIONS = {
    "ho-chi-minh-city": {
        "slug": "ho-chi-minh-city",
        "city": "Ho Chi Minh City",
        "country": "Vietnam",
        "headline": "Fast-moving neighborhoods, strong everyday convenience, and broad housing choice.",
        "transcript": (
            "Ho Chi Minh City is a practical base for people who want urban energy, international schools, "
            "private healthcare, and a wide range of apartments and houses. Roamstead compares real listings "
            "against your budget and daily-life priorities, while leaving legal and property claims clearly marked for verification."
        ),
        "video_prompt": (
            "Eight-second cinematic, realistic city orientation of Ho Chi Minh City, Vietnam at golden hour. "
            "Show a smooth street-level-to-skyline sequence with modern apartments, tree-lined streets, riverfront, "
            "local food storefronts and ordinary city movement. No text, no logos, no property listing, no identifiable people, "
            "no luxury exaggeration. Documentary travel-film style, stable camera, 16:9."
        ),
    },
    "bangkok": {
        "slug": "bangkok",
        "city": "Bangkok",
        "country": "Thailand",
        "headline": "Dense transit, global services, and distinct neighborhoods at many price points.",
        "transcript": (
            "Bangkok combines major transit links, international schools, private hospitals, and a deep rental market. "
            "Neighborhood tradeoffs can change block by block, so Roamstead keeps the search grounded in your hard requirements "
            "and makes every softer preference visible and editable."
        ),
        "video_prompt": (
            "Eight-second cinematic, realistic city orientation of Bangkok, Thailand in soft morning light. "
            "Show a smooth sequence of elevated rail, modern residential towers, a calm neighborhood street, market food stalls, "
            "and the river. No text, no logos, no property listing, no identifiable people, no tourism montage exaggeration. "
            "Documentary travel-film style, stable camera, 16:9."
        ),
    },
    "kuala-lumpur": {
        "slug": "kuala-lumpur",
        "city": "Kuala Lumpur",
        "country": "Malaysia",
        "headline": "Modern infrastructure, multilingual daily life, and green residential districts.",
        "transcript": (
            "Kuala Lumpur offers modern infrastructure, international education, varied food access, and residential areas that range "
            "from central high-rises to quieter houses. Roamstead helps a mover compare those tradeoffs using the same profile and evidence rules across markets."
        ),
        "video_prompt": (
            "Eight-second cinematic, realistic city orientation of Kuala Lumpur, Malaysia after light rain. "
            "Show a smooth sequence of the modern skyline, green residential streets, rail transit, apartment buildings and diverse food storefronts. "
            "No text, no logos, no property listing, no identifiable people, no luxury exaggeration. Documentary travel-film style, stable camera, 16:9."
        ),
    },
}


def city_orientation(slug: str) -> dict | None:
    base = CITY_ORIENTATIONS.get(slug)
    if not base:
        return None
    record = get_document("city_orientations", slug) or {}
    result = {
        **deepcopy(base),
        **record,
        "video_model": record.get("video_model", VIDEO_MODEL),
        "narration_model": record.get("narration_model", NARRATION_MODEL),
        "video_status": record.get("video_status", "UNAVAILABLE"),
        "narration_status": record.get("narration_status", "UNAVAILABLE"),
        "disclaimer": DISCLAIMER,
    }
    result.pop("video_prompt", None)
    if result["video_status"] == "READY":
        result["video_url"] = f"/api/v1/city-orientations/{slug}/video"
    if result["narration_status"] == "READY":
        result["audio_url"] = f"/api/v1/city-orientations/{slug}/audio"
    return result


def all_city_orientations() -> list[dict]:
    return [city_orientation(slug) for slug in CITY_ORIENTATIONS]
