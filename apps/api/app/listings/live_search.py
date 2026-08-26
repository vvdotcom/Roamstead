from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from google import genai
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search
from google.genai import types
from pydantic import ValidationError
from dotenv import load_dotenv

from ..models import Listing


API_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = Path(__file__).resolve()
PROJECT_ROOT = _MODULE_PATH.parents[4] if len(_MODULE_PATH.parents) > 4 else Path.cwd()

# Support a shared project-root .env while allowing an API-local file to win.
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(API_ROOT / ".env", override=True)


PRICE_BANDS: dict[str, dict[str, tuple[int, int | None]]] = {
    "BUY": {
        "LOW": (1, 3_000_000_000),
        "MEDIUM": (3_000_000_000, 7_000_000_000),
        "HIGH": (7_000_000_000, 20_000_000_000),
        "ULTRA_HIGH": (20_000_000_000, None),
    },
    "RENT": {
        "LOW": (1, 10_000_000),
        "MEDIUM": (10_000_000, 25_000_000),
        "HIGH": (25_000_000, 60_000_000),
        "ULTRA_HIGH": (60_000_000, None),
    },
}

NEIGHBORHOOD_ALIASES = {
    "thu-thiem": ("thu thiem", "thủ thiêm", "thu duc", "thủ đức"),
    "binh-thanh": ("binh thanh", "bình thạnh"),
    "phu-my-hung": ("phu my hung", "phú mỹ hưng", "district 7", "quận 7", "quan 7"),
    "nha-be": ("nha be", "nhà bè"),
}


class LiveListingConfigurationError(RuntimeError):
    pass


class LiveListingSearchError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _gemini_configured() -> bool:
    has_api_key = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    has_vertex = bool(
        (os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID"))
        and (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_GENAI_USE_VERTEXAI"))
    )
    return has_api_key or has_vertex


def _price_band(mode: str, price_vnd: int) -> str:
    for band, (minimum, maximum) in PRICE_BANDS[mode].items():
        if price_vnd >= minimum and (maximum is None or price_vnd < maximum):
            return band
    return "LOW"


def _neighborhood_id(district: str, address: str | None) -> str:
    haystack = f"{district} {address or ''}".casefold()
    for neighborhood_id, aliases in NEIGHBORHOOD_ALIASES.items():
        if any(alias in haystack for alias in aliases):
            return neighborhood_id
    return "hcmc"


def _is_batdongsan_url(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").lower()
    except ValueError:
        return False
    # A listing source must be a human-viewable Batdongsan page. Asset hosts
    # such as file4.batdongsan.com.vn are valid image origins, but never valid
    # values for the property-detail provenance action.
    return host in {"batdongsan.com.vn", "www.batdongsan.com.vn"}


def _is_batdongsan_detail_url(value: str) -> bool:
    if not _is_batdongsan_url(value):
        return False
    return bool(re.search(r"-(?:pr|p)\d+(?:$|[/?#])", value, re.IGNORECASE))


def _is_google_grounding_redirect(value: str) -> bool:
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    return host == "vertexaisearch.cloud.google.com" and bool(
        re.fullmatch(r"/grounding-api-redirect/AUZIYQ[A-Za-z0-9_-]{70,}={0,2}", parsed.path)
    )


def _is_direct_image_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return _is_google_grounding_redirect(value) or (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and bool(re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", parsed.path + (f"?{parsed.query}" if parsed.query else ""), re.IGNORECASE))
    )


BATDONGSAN_UPLOAD_STAMP = re.compile(
    r"/(?:\d+x\d+/)?(\d{4})/(\d{2})/(\d{2})/(\d{8})(\d{6})-[^/]+\.(?:jpe?g|png|webp)$",
    re.IGNORECASE,
)


def _batdongsan_upload_time(value: str) -> datetime | None:
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not re.fullmatch(r"file\d*\.batdongsan\.com\.vn", host):
        return None
    match = BATDONGSAN_UPLOAD_STAMP.search(parsed.path)
    if not match or match.group(1) + match.group(2) + match.group(3) != match.group(4):
        return None
    try:
        return datetime.strptime(match.group(4) + match.group(5), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalized_source_url(value: str) -> str:
    return value.strip().rstrip("/")


def _image_map_from_payload(payload: dict[str, Any], requested_urls: set[str]) -> dict[str, str]:
    images = payload.get("images")
    if not isinstance(images, list):
        return {}
    matches: dict[str, str] = {}
    for item in images:
        if not isinstance(item, dict):
            continue
        source_url = _normalized_source_url(str(item.get("source_url") or ""))
        image_url = str(item.get("image_url") or "").strip()
        if source_url in requested_urls and _is_direct_image_url(image_url):
            matches[source_url] = image_url
    return matches


def _ascii_fold(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", value) if not unicodedata.combining(character)
    ).casefold()


VIETNAMESE_LISTING_TERMS = re.compile(
    r"\b(can ho|cho thue|nha dat|nha rieng|ban nha|phong ngu|mat tien|biet thu|chinh chu|duong|phuong|quan)\b",
    re.IGNORECASE,
)

CURRENCY_PRICE_TEXT = re.compile(
    r"\s*[,;:\-–—]?\s*(?:price\s*)?\d[\d.,]*\s*(?:thousand|million|billion)?\s*(?:vnd|usd|₫|\$)(?:\s*/\s*(?:month|mo))?",
    re.IGNORECASE,
)


def _has_untranslated_listing_text(value: str | None) -> bool:
    return bool(value and VIETNAMESE_LISTING_TERMS.search(_ascii_fold(value)))


def _without_currency_price(value: str) -> str:
    cleaned = CURRENCY_PRICE_TEXT.sub("", value)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" ,;:-–—")


def _english_district(value: str) -> str:
    folded = _ascii_fold(value).strip()
    if "thu duc" in folded:
        return "Thu Duc City"
    numbered = re.search(r"(?:quan|district)\s*(\d+)", folded)
    if numbered:
        return f"District {numbered.group(1)}"
    named = re.search(r"quan\s+([a-z ]+)", folded)
    if named:
        return f"{named.group(1).strip().title()} District"
    if "ho chi minh" in folded or folded in {"hcmc", "tphcm", "tp hcm"}:
        return "Ho Chi Minh City"
    return value.strip()


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise LiveListingSearchError("Gemini did not return a JSON listing result.")
    return json.loads(cleaned[start : end + 1])


def _used_google_search(response: Any) -> bool:
    """Reject model-memory answers when the request was meant to be live."""
    steps = getattr(response, "steps", None) or []
    step_types = {getattr(step, "type", None) for step in steps}
    has_steps = "google_search_call" in step_types and any(
        getattr(step, "type", None) == "google_search_result"
        and not bool(getattr(step, "is_error", False))
        for step in steps
    )
    usage = getattr(response, "usage", None)
    grounding_counts = getattr(usage, "grounding_tool_count", None) or []
    has_usage = any(
        getattr(item, "type", None) == "google_search" and int(getattr(item, "count", 0) or 0) > 0
        for item in grounding_counts
    )
    return has_steps or has_usage


def _simple_property_type(value: object) -> str | None:
    normalized = str(value or "").casefold().replace("-", " ")
    if any(term in normalized for term in ("apartment", "condo", "studio", "flat")):
        return "Apartment"
    if any(term in normalized for term in ("house", "home", "townhome", "villa")):
        return "House"
    return None


def _normalize(raw: dict[str, Any], mode: str, grounded_domains: set[str]) -> Listing | None:
    source_url = str(raw.get("source_url") or "").strip()
    if not _is_batdongsan_url(source_url):
        return None

    try:
        price_vnd = int(float(str(raw.get("price_vnd", "0")).replace(",", "")))
    except (TypeError, ValueError):
        return None
    if price_vnd <= 0:
        return None

    district = _english_district(str(raw.get("district") or "Ho Chi Minh City"))[:100]
    address = str(raw.get("address") or "").strip()[:180] or None
    source_title_text = _without_currency_price(
        str(raw.get("source_title") or raw.get("title") or "").strip()
    )
    source_title = source_title_text[:200] or None
    title = _without_currency_price(str(raw.get("title") or source_title or "Live property listing").strip())[:180]
    if _has_untranslated_listing_text(source_title):
        source_title = title
    property_type = _simple_property_type(raw.get("property_type"))
    if not property_type:
        return None
    image_url = str(raw.get("image_url") or "").strip()
    if not _is_direct_image_url(image_url):
        return None
    if any(_has_untranslated_listing_text(value) for value in (title, address, property_type)):
        return None

    def optional_number(key: str, cast):
        value = raw.get(key)
        if value in (None, "", "unknown", "N/A"):
            return None
        try:
            parsed = cast(float(str(value).replace(",", "")))
            return parsed if parsed >= 0 else None
        except (TypeError, ValueError):
            return None

    digest = hashlib.sha256(f"{source_url}|{image_url}".encode("utf-8")).hexdigest()[:20]
    try:
        return Listing(
            id=f"bds-{digest}",
            neighborhood_id=_neighborhood_id(district, address),
            title=title,
            transaction_mode=mode,
            price_vnd=price_vnd,
            price_usd=max(1, round(price_vnd / int(os.getenv("VND_PER_USD", "26000")))),
            price_band=_price_band(mode, price_vnd),
            district=district,
            address=address,
            beds=optional_number("beds", int),
            baths=optional_number("baths", int),
            area_sqm=optional_number("area_sqm", float),
            image_url=image_url,
            property_type=property_type,
            source_url=source_url,
            source_title=source_title,
            source_checked_at=_utc_now().isoformat(),
            demo=False,
        )
    except ValidationError:
        return None


SEARCH_FOCUSES = (
    "Districts 1, 3, 4, Binh Thanh, and Phu Nhuan",
    "Thu Duc City (including former District 2 and District 9), District 7, and Nha Be",
    "Tan Binh, Go Vap, Binh Tan, Tan Phu, District 10, and District 11",
    "all remaining Ho Chi Minh City districts, favoring highly relevant result pages",
)

SEARCH_VARIANTS: dict[str, tuple[str, ...]] = {
    "BUY": (
        "apartments and condominiums",
        "townhouses and street-front houses",
        "whole houses and townhomes",
        "villas and compound homes",
        "houses in residential neighborhoods",
        "newly posted owner-listed properties",
    ),
    "RENT": (
        "apartments and condominiums",
        "serviced apartments and studios",
        "townhouses and whole houses",
        "villas and compound homes",
        "shophouses and street-front homes",
        "newly posted owner-listed properties",
    ),
}


def _band_prompt(
    mode: str,
    band: str,
    target: int,
    batch_index: int = 0,
    excluded_urls: tuple[str, ...] = (),
) -> str:
    minimum, maximum = PRICE_BANDS[mode][band]
    if mode == "BUY":
        transaction = "properties for sale"
        price_period = "total sale price"
        path_hint = "nha-dat-ban"
    else:
        transaction = "properties for rent"
        price_period = "monthly rent"
        path_hint = "nha-dat-cho-thue"
    range_text = f"from {minimum:,} VND"
    if maximum is not None:
        range_text += f" up to but not including {maximum:,} VND"
    else:
        range_text += " and above"

    exclusions = ""
    if excluded_urls:
        exclusions = "\nDo not return any of these URLs already saved in this band:\n" + "\n".join(excluded_urls)

    return f"""
Use Google Search to find up to {target} distinct, currently accessible Batdongsan.com.vn listing detail pages for {transaction} in Ho Chi Minh City.
Use no more than four Google Search calls for this batch. Return fewer listings rather than exceeding the tool-call limit.
Search only the batdongsan.com.vn domain, prioritizing URLs under or related to /{path_hint}.
This batch must cover the {band} band: {price_period} {range_text}.
For search batch {batch_index + 1}, prioritize {SEARCH_FOCUSES[batch_index % len(SEARCH_FOCUSES)]}.

Return a listing only when the search result or indexed page explicitly supplies a numeric price and a direct Batdongsan listing URL. Do not infer, estimate, invent, or repeat a property. Omit unavailable fields.
Translate every user-facing field into natural English: title, district, address, and source_title. Keep Vietnamese proper names only where needed, but translate words such as căn hộ, cho thuê, đường, phường, and quận. Classify property_type as exactly "Apartment" or "House"; townhouses, villas, and shophouses are House. Omit land and any listing that does not fit either category. Do not return untranslated Vietnamese listing text. The title and source_title must describe the property without including a price, currency, or phone number; price_vnd is the only price field.
{exclusions}

Return only one compact JSON object with this exact shape:
{{"listings":[{{"title":"English title","price_vnd":123000000,"district":"District 7","address":"English address or empty","beds":2,"baths":2,"area_sqm":80,"property_type":"Apartment","source_url":"https://batdongsan.com.vn/...","source_title":"English source-title translation"}}]}}
""".strip()


def _image_prompt(source_urls: list[str]) -> str:
    urls = "\n".join(source_urls)
    return f"""
Use Google Image Search to locate one real property photo for each exact Batdongsan.com.vn listing URL below.
You MUST call the supplied Google Search tool before answering. Do not answer from memory.
The image must belong to that exact listing. For image_url, prefer the exact HTTPS vertexaisearch.cloud.google.com grounding redirect emitted by the tool because the Batdongsan origin asset may block direct downloads. If no grounding redirect is available, use the original image URL emitted by the tool.
Never return a logo, map, icon, placeholder, generic building photo, generated image, listing-page URL, or an image from a different property. Never invent a URL. Omit a listing if its exact property photo cannot be verified.

Return only one compact JSON object with this exact shape:
{{"images":[{{"source_url":"exact input URL","image_url":"https://cdn.batdongsan.com.vn/.../photo.jpg"}}]}}

Exact listing URLs:
{urls}
""".strip()


def _gallery_prompt(listing: Listing, limit: int, attempt: int) -> str:
    return f"""
Use Google Image Search to retrieve up to {limit} distinct photographs belonging to this exact Batdongsan.com.vn listing:
URL: {listing.source_url}
Title: {listing.title}
Address: {listing.address or listing.district}
Property type: {listing.property_type}

You MUST use the supplied Google Search tool and search the quoted exact full URL. Do not search by project name or title, do not answer from memory, and do not borrow photos from a project overview or another unit. Every image result's source page URL must normalize to the exact URL above. Search the indexed listing gallery for useful views such as the exterior, living room, kitchen, bedrooms, bathrooms, balcony/view, and amenities.

Return actual photographs of the advertised property only. Exclude ownership certificates, title deeds, contracts, legal documents, screenshots, text/price/contact cards, agent graphics, logos, maps, floor plans, collages, generic project renderings, stock photos, and duplicates. The first result must be the strongest exterior or interior property photograph; it must never be a document, floor plan, map, rendering, or graphic. On retrieval pass {attempt + 1}, favor rooms or views not already prominent in the result set.

For image_url, copy the exact HTTPS vertexaisearch.cloud.google.com grounding redirect emitted for that image when available; otherwise copy the exact original image URL emitted by the tool. Never invent or rewrite a URL. Omit anything that cannot be tied to the exact listing.

Return only one compact JSON object with this exact shape:
{{"images":[{{"source_url":"{listing.source_url}","image_url":"https://...","kind":"exterior","is_property_photo":true,"is_exact_listing":true}}]}}
""".strip()


BLOCKED_GALLERY_KINDS = {
    "certificate",
    "collage",
    "contact card",
    "document",
    "floor plan",
    "graphic",
    "legal document",
    "logo",
    "map",
    "project rendering",
    "rendering",
    "screenshot",
    "stock photo",
    "text card",
    "title deed",
}


def _gallery_urls_from_payload(payload: dict[str, Any], exact_source_url: str | None = None) -> list[str]:
    images = payload.get("images")
    if not isinstance(images, list):
        return []
    urls: list[str] = []
    for item in images:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().casefold().replace("_", " ")
        image_url = str(item.get("image_url") or "").strip()
        source_url = _normalized_source_url(str(item.get("source_url") or ""))
        if (
            item.get("is_property_photo") is not True
            or item.get("is_exact_listing") is not True
            or (exact_source_url and source_url != _normalized_source_url(exact_source_url))
            or kind in BLOCKED_GALLERY_KINDS
            or not _is_direct_image_url(image_url)
        ):
            continue
        urls.append(image_url)
    return list(dict.fromkeys(urls))


def _image_band_prompt(
    mode: str,
    band: str,
    target: int,
    batch_index: int,
    excluded_urls: tuple[str, ...],
) -> str:
    minimum, maximum = PRICE_BANDS[mode][band]
    transaction = "for sale" if mode == "BUY" else "for rent"
    price_label = "total sale price" if mode == "BUY" else "monthly rent"
    search_hint = (
        'Use Vietnamese discovery terms such as "bán căn hộ TP HCM", "nhà đất bán", and site:batdongsan.com.vn/nha-dat-ban.'
        if mode == "BUY"
        else 'Use discovery terms such as "cho thuê căn hộ TP HCM" and site:batdongsan.com.vn/nha-dat-cho-thue.'
    )
    band_search_terms = {
        "BUY": {
            "LOW": 'Include the exact Vietnamese price phrase "giá dưới 3 tỷ".',
            "MEDIUM": 'Include "giá từ 3 tỷ đến 7 tỷ".',
            "HIGH": 'Include "giá từ 7 tỷ đến 20 tỷ".',
            "ULTRA_HIGH": 'Include "giá trên 20 tỷ".',
        },
        "RENT": {
            "LOW": 'Include "giá dưới 10 triệu/tháng".',
            "MEDIUM": 'Include "giá từ 10 đến 25 triệu/tháng".',
            "HIGH": 'Include "giá từ 25 đến 60 triệu/tháng".',
            "ULTRA_HIGH": 'Include "giá trên 60 triệu/tháng".',
        },
    }[mode][band]
    range_text = f"at least {minimum:,} VND"
    if maximum is not None:
        range_text += f" and less than {maximum:,} VND"
    exclusions = "\n".join(excluded_urls)
    return f"""
Use Google Image Search to find up to {target} currently active (August 2026) Batdongsan.com.vn inventory results for Ho Chi Minh City properties {transaction}. Every result must have an actual property photo and an explicit numeric price.
You MUST call the supplied Google Search tool before answering. Use both web and image results; do not answer from memory.
{search_hint}
{band_search_terms}
This is the {band} price band: {price_label} must be {range_text}.
For batch {batch_index + 1}, prioritize {SEARCH_FOCUSES[batch_index % len(SEARCH_FOCUSES)]}.
In this batch specifically search for {SEARCH_VARIANTS[mode][batch_index % len(SEARCH_VARIANTS[mode])]}; do not broaden beyond the requested transaction mode or price band.

Return only real search-tool results. For every result, copy the exact image-search source page URL and exact original image URL emitted by the tool. The result source must be on batdongsan.com.vn. Prefer recently indexed images and omit old or unavailable results. Do not synthesize, rewrite, or guess either URL. Every result must identify one inventory card: real photo, numeric price, title or project, and district. Do not use a logo, map, project rendering, generic building photo, generated image, another website, or a different property.

Return a result only when search evidence explicitly supplies a numeric VND price in the requested band. Never use placeholder values. Translate title, district, address, and source_title into natural English. Classify property_type as exactly "Apartment" or "House"; townhouses, villas, and shophouses are House. Omit land and any listing that does not fit either category. Omit price/currency and phone numbers from title fields.

Do not return inventory cards using these already-saved image URLs:
{exclusions or "None"}

Return only compact JSON:
{{"listings":[{{"title":"English property title","price_vnd":18000000,"district":"District 7","address":"English address","beds":2,"baths":2,"area_sqm":75,"property_type":"Apartment","source_url":"exact listing source or grounding redirect URL","image_url":"exact image grounding redirect URL","source_title":"English source title"}}]}}
""".strip()


def _detail_match_prompt(mode: str, raw_listings: list[dict[str, Any]]) -> str:
    candidates = [
        {
            "index": index,
            "title": item.get("title"),
            "price_vnd": item.get("price_vnd"),
            "district": item.get("district"),
            "address": item.get("address"),
            "property_type": item.get("property_type"),
            "image_result_source": item.get("source_url"),
        }
        for index, item in enumerate(raw_listings)
    ]
    return f"""
Use Google Search to match each candidate below to the exact Batdongsan.com.vn Ho Chi Minh City property detail page for {"sale" if mode == "BUY" else "rent"}.
The detail URL must identify the same property using its title/project, exact numeric VND price, district/address, and property type. It must end with a property ID such as -pr12345678 or -p113456789. Never return a category, search, project overview, another property, or another domain. Omit any candidate that cannot be matched confidently. Do not invent URLs.

Candidates:
{json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))}

Return only compact JSON:
{{"matches":[{{"index":0,"source_url":"exact Batdongsan detail URL or its Google grounding redirect"}}]}}
""".strip()


class GeminiLiveListingSearch:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], tuple[datetime, list[Listing]]] = {}
        self._cache_ttl = timedelta(minutes=int(os.getenv("LIVE_LISTING_CACHE_MINUTES", "30")))

    @property
    def configured(self) -> bool:
        return _gemini_configured()

    def _image_search_client(self) -> genai.Client:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            return genai.Client(api_key=api_key)
        project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
        location = os.getenv("VERTEX_LOCATION") or os.getenv("GCP_REGION") or "us-central1"
        return genai.Client(vertexai=True, project=project, location=location)

    async def _find_image_urls(self, source_urls: list[str]) -> dict[str, str]:
        requested_urls = {_normalized_source_url(url) for url in source_urls if _is_batdongsan_url(url)}
        if not requested_urls:
            return {}
        client = self._image_search_client()
        response = await asyncio.wait_for(
            client.aio.interactions.create(
                model=os.getenv("ROAMSTEAD_GEMINI_IMAGE_SEARCH_MODEL", "gemini-3.1-flash-image"),
                input=_image_prompt(sorted(requested_urls)),
                tools=[{"type": "google_search", "search_types": ["web_search", "image_search"]}],
                response_format=[{"type": "text"}],
            ),
            timeout=max(180.0, float(os.getenv("LIVE_LISTING_SEARCH_TIMEOUT_SECONDS", "180"))),
        )
        if not _used_google_search(response):
            return {}
        try:
            payload = _extract_json(response.output_text or "")
        except (LiveListingSearchError, json.JSONDecodeError):
            payload = {}
        matches = _image_map_from_payload(payload, requested_urls)
        if len(requested_urls) == 1:
            redirect_candidates = re.findall(
                r"https://vertexaisearch\.cloud\.google\.com/grounding-api-redirect/AUZIYQ[A-Za-z0-9_-]{70,}={0,2}",
                response.output_text or "",
            )
            for step in getattr(response, "steps", None) or []:
                if getattr(step, "type", None) != "model_output":
                    continue
                for block in getattr(step, "content", None) or []:
                    for annotation in getattr(block, "annotations", None) or []:
                        candidate = str(getattr(annotation, "url", "") or "")
                        if _is_google_grounding_redirect(candidate):
                            redirect_candidates.append(candidate)
            if redirect_candidates:
                matches[next(iter(requested_urls))] = redirect_candidates[0]
        return matches

    async def _find_image_urls_reliably(self, source_urls: list[str]) -> dict[str, str]:
        attempts = max(1, min(5, int(os.getenv("LIVE_LISTING_IMAGE_SEARCH_ATTEMPTS", "2"))))
        base_delay = max(0.0, float(os.getenv("LIVE_LISTING_RETRY_BASE_SECONDS", "2")))
        for attempt in range(attempts):
            try:
                matches = await self._find_image_urls(source_urls)
                if matches:
                    return matches
            except Exception:
                pass
            if attempt + 1 < attempts and base_delay:
                await asyncio.sleep(min(30.0, base_delay * (2**attempt)))
        return {}

    async def find_gallery_urls(self, listing: Listing, limit: int | None = None) -> list[str]:
        """Find search-grounded, exact-listing property photos in display order."""
        if not self.configured:
            raise LiveListingConfigurationError(
                "Gallery search requires GEMINI_API_KEY or configured Vertex AI credentials."
            )
        requested_limit = max(
            1,
            min(20, limit or int(os.getenv("LISTING_GALLERY_MAX_IMAGES", "10"))),
        )
        attempts = max(1, min(3, int(os.getenv("LISTING_GALLERY_SEARCH_ATTEMPTS", "2"))))
        base_delay = max(0.0, float(os.getenv("LIVE_LISTING_RETRY_BASE_SECONDS", "2")))
        client = self._image_search_client()
        collected: list[str] = []
        for attempt in range(attempts):
            try:
                response = await asyncio.wait_for(
                    client.aio.interactions.create(
                        model=os.getenv("ROAMSTEAD_GEMINI_IMAGE_SEARCH_MODEL", "gemini-3.1-flash-image"),
                        input=_gallery_prompt(listing, requested_limit, attempt),
                        tools=[{"type": "google_search", "search_types": ["web_search", "image_search"]}],
                        response_format=[{"type": "text"}],
                    ),
                    timeout=max(180.0, float(os.getenv("LIVE_LISTING_SEARCH_TIMEOUT_SECONDS", "180"))),
                )
                if not _used_google_search(response):
                    raise LiveListingSearchError("Gemini did not ground the gallery in Google Search.")
                if os.getenv("LISTING_GALLERY_DEBUG") == "1":
                    print(f"gallery response {listing.id}: {(response.output_text or '')[:4000]}", flush=True)
                payload = _extract_json(response.output_text or "")
                collected.extend(_gallery_urls_from_payload(payload, listing.source_url))
                collected = list(dict.fromkeys(collected))
                if len(collected) >= requested_limit:
                    break
            except (TimeoutError, LiveListingSearchError, json.JSONDecodeError):
                pass
            if attempt + 1 < attempts and base_delay:
                await asyncio.sleep(min(30.0, base_delay * (2**attempt)))
        return await self.filter_gallery_urls_by_upload_batch(
            listing,
            list(dict.fromkeys([*listing.image_urls, *collected]))[:requested_limit],
        )

    async def filter_gallery_urls_by_upload_batch(
        self,
        listing: Listing,
        candidate_urls: list[str],
    ) -> list[str]:
        """Require every gallery photo to match the listing cover's upload batch.

        Image search can confuse another unit in the same development with the
        exact listing. Batdongsan gallery files are uploaded together and carry
        their upload timestamp in the official file host path. Using the saved
        exact-listing cover as the anchor rejects other portals, project stock,
        and same-project photos uploaded in a different session.
        """
        urls = list(dict.fromkeys([listing.image_url, *candidate_urls]))
        timeout = max(10.0, float(os.getenv("LISTING_IMAGE_DOWNLOAD_TIMEOUT_SECONDS", "30")))
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Roamstead/1.0)"},
        ) as client:
            async def resolve(url: str) -> tuple[str, datetime | None]:
                try:
                    response = await client.get(url)
                except httpx.HTTPError:
                    return url, None
                if response.status_code != 200:
                    return url, None
                return url, _batdongsan_upload_time(str(response.url))

            resolved = await asyncio.gather(*(resolve(url) for url in urls))

        anchor_time = resolved[0][1]
        if not anchor_time:
            return []
        maximum_gap = timedelta(
            minutes=max(1, int(os.getenv("LISTING_GALLERY_UPLOAD_WINDOW_MINUTES", "120")))
        )
        resolved_times = {url: upload_time for url, upload_time in resolved}
        accepted: list[str] = []
        for url in dict.fromkeys(candidate_urls):
            upload_time = resolved_times.get(url)
            if upload_time and abs(upload_time - anchor_time) <= maximum_gap:
                accepted.append(url)
        return accepted

    async def _resolve_source_urls(self, raw_listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=max(5.0, float(os.getenv("LIVE_LISTING_REDIRECT_TIMEOUT_SECONDS", "20"))),
            headers={"User-Agent": "Mozilla/5.0 (compatible; Roamstead/1.0)"},
        ) as client:
            async def resolve(item: dict[str, Any]) -> dict[str, Any] | None:
                source_url = str(item.get("source_url") or "").strip()
                if _is_batdongsan_url(source_url):
                    return item
                if not _is_google_grounding_redirect(source_url):
                    return None
                try:
                    response = await client.get(source_url)
                except httpx.HTTPError:
                    return None
                final_url = _normalized_source_url(str(response.url))
                if not _is_batdongsan_url(final_url):
                    return None
                return {**item, "source_url": final_url}

            resolved = await asyncio.gather(*(resolve(item) for item in raw_listings))
        return [item for item in resolved if item is not None]

    async def _match_detail_urls(
        self,
        mode: str,
        raw_listings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not raw_listings:
            return []
        client = self._image_search_client()
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash"),
                    contents=_detail_match_prompt(mode, raw_listings),
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    ),
                ),
                timeout=max(180.0, float(os.getenv("LIVE_LISTING_SEARCH_TIMEOUT_SECONDS", "180"))),
            )
            payload = _extract_json(response.text or "")
        except (TimeoutError, LiveListingSearchError, json.JSONDecodeError):
            return []
        matches = payload.get("matches") if payload else None
        if not isinstance(matches, list):
            return []

        detailed: list[dict[str, Any]] = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            try:
                index = int(match.get("index"))
            except (TypeError, ValueError):
                continue
            source_url = str(match.get("source_url") or "").strip()
            if not 0 <= index < len(raw_listings):
                continue
            if not (_is_batdongsan_detail_url(source_url) or _is_google_grounding_redirect(source_url)):
                continue
            detailed.append({**raw_listings[index], "source_url": source_url})
        return detailed

    async def _attach_image_urls(self, raw_listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_url = {
            _normalized_source_url(str(item.get("source_url") or "")): item
            for item in raw_listings
            if _is_batdongsan_url(str(item.get("source_url") or ""))
        }
        if not by_url:
            return []

        chunk_size = max(1, min(10, int(os.getenv("LIVE_LISTING_IMAGE_BATCH_SIZE", "1"))))
        image_urls: dict[str, str] = {}
        urls = list(by_url)
        for start in range(0, len(urls), chunk_size):
            image_urls.update(await self._find_image_urls_reliably(urls[start : start + chunk_size]))

        # Batch search can omit a valid photo. Retry only missing records in
        # smaller groups; anything still missing stays out of the catalog.
        missing = [url for url in urls if url not in image_urls]
        retry_size = max(1, min(3, int(os.getenv("LIVE_LISTING_IMAGE_RETRY_BATCH_SIZE", "1"))))
        retry_cooldown = max(0.0, float(os.getenv("LIVE_LISTING_IMAGE_RETRY_COOLDOWN_SECONDS", "1")))
        for start in range(0, len(missing), retry_size):
            if retry_cooldown and start:
                await asyncio.sleep(retry_cooldown)
            image_urls.update(await self._find_image_urls_reliably(missing[start : start + retry_size]))

        enriched: list[dict[str, Any]] = []
        for source_url, item in by_url.items():
            image_url = image_urls.get(source_url)
            if image_url:
                enriched.append({**item, "source_url": source_url, "image_url": image_url})
        return enriched

    async def search(
        self,
        mode: str,
        limit: int = 100,
        refresh: bool = False,
        existing_items: list[Listing] | None = None,
        on_batch: Callable[[list[Listing]], Awaitable[list[Listing]]] | None = None,
    ) -> list[Listing]:
        if not self.configured:
            raise LiveListingConfigurationError(
                "Live listing search requires GEMINI_API_KEY or configured Vertex AI credentials. No synthetic listings are used."
            )
        cache_key = (mode, limit)
        cached = self._cache.get(cache_key)
        if cached and not refresh and _utc_now() - cached[0] < self._cache_ttl:
            return cached[1][:limit]

        per_band = max(1, (limit + 3) // 4)
        concurrency = max(1, int(os.getenv("LIVE_LISTING_SEARCH_CONCURRENCY", "1")))
        cooldown_seconds = max(0.0, float(os.getenv("LIVE_LISTING_SEARCH_COOLDOWN_SECONDS", "5")))
        retry_base_seconds = max(0.0, float(os.getenv("LIVE_LISTING_RETRY_BASE_SECONDS", "2")))
        semaphore = asyncio.Semaphore(concurrency)

        batch_size = max(1, min(10, int(os.getenv("LIVE_LISTING_BATCH_SIZE", "6"))))

        existing_items = existing_items or []

        async def search_band(band: str) -> list[Listing]:
            async with semaphore:
                collected: dict[str, Listing] = {}
                errors: list[Exception] = []
                existing_band_items = [item for item in existing_items if item.price_band == band]
                existing_source_urls = {item.source_url for item in existing_band_items}
                band_target = max(0, per_band - len(existing_band_items))
                max_batches = max(
                    ((band_target + batch_size - 1) // batch_size) + 1,
                    int(os.getenv("LIVE_LISTING_MAX_BATCHES_PER_BAND", "12")),
                )
                consecutive_errors = 0
                for batch_index in range(max_batches):
                    remaining = band_target - len(collected)
                    if remaining <= 0:
                        break
                    try:
                        batch = await self._search_band(
                            mode,
                            band,
                            min(batch_size, remaining),
                            batch_index=len(existing_band_items) + batch_index,
                            excluded_urls=tuple(
                                sorted(existing_source_urls | {item.source_url for item in collected.values()})
                            ),
                        )
                        if on_batch and batch:
                            batch = await on_batch(batch)
                        collected.update({item.id: item for item in batch})
                        consecutive_errors = 0
                    except Exception as exc:
                        errors.append(exc)
                        consecutive_errors += 1
                    delay = cooldown_seconds
                    if consecutive_errors:
                        delay = max(delay, min(60.0, retry_base_seconds * (2 ** min(4, consecutive_errors - 1))))
                    if delay:
                        await asyncio.sleep(delay)
                if not collected and errors:
                    raise errors[0]
                return list(collected.values())

        results = await asyncio.gather(
            *(search_band(band) for band in PRICE_BANDS[mode]),
            return_exceptions=True,
        )
        listings: list[Listing] = []
        errors: list[str] = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                listings.extend(result)

        unique = {item.id: item for item in listings}
        ordered = sorted(unique.values(), key=lambda item: (list(PRICE_BANDS[mode]).index(item.price_band), item.price_vnd))
        if not ordered and errors:
            raise LiveListingSearchError("Gemini live search returned no validated Batdongsan listings. " + errors[0])
        self._cache[cache_key] = (_utc_now(), ordered[:limit])
        return ordered[:limit]

    async def _search_band(
        self,
        mode: str,
        band: str,
        target: int,
        batch_index: int = 0,
        excluded_urls: tuple[str, ...] = (),
    ) -> list[Listing]:
        client = self._image_search_client()
        response = await asyncio.wait_for(
            client.aio.interactions.create(
                model=os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash"),
                input=_band_prompt(mode, band, target, batch_index, excluded_urls),
                tools=[{"type": "google_search"}],
                response_format=[{"type": "text"}],
            ),
            timeout=max(180.0, float(os.getenv("LIVE_LISTING_SEARCH_TIMEOUT_SECONDS", "180"))),
        )
        if not _used_google_search(response):
            raise LiveListingSearchError("Gemini did not execute Google Search for this listing batch.")
        try:
            payload = _extract_json(response.output_text or "")
        except (LiveListingSearchError, json.JSONDecodeError) as exc:
            raise LiveListingSearchError("Gemini Search did not return a JSON listing result.") from exc
        raw_listings = payload.get("listings")
        if not isinstance(raw_listings, list):
            raise LiveListingSearchError("Gemini Search returned an invalid listings collection.")
        raw_dicts = [item for item in raw_listings if isinstance(item, dict)]
        resolved = await self._resolve_source_urls(raw_dicts)
        enriched = await self._attach_image_urls(resolved)
        normalized = [_normalize(item, mode, set()) for item in enriched]
        return [item for item in normalized if item is not None and item.price_band == band]

        # Retained below as the fallback ADK web-search implementation for
        # environments where image-first retrieval is later disabled.
        agent = Agent(
            name=f"live_listing_search_{mode.lower()}_{band.lower()}",
            model=os.getenv("ROAMSTEAD_GEMINI_MODEL", "gemini-3.5-flash"),
            description="Finds current, sourced real-estate listings using Google Search.",
            instruction=(
                "You are a retrieval agent. Use Google Search for every request. Return only source-backed facts in the requested JSON shape. "
                "Never invent a listing or use remembered property data. Translate every presentation field into natural English."
            ),
            tools=[google_search],
            mode="chat",
            timeout=max(180.0, float(os.getenv("LIVE_LISTING_SEARCH_TIMEOUT_SECONDS", "180"))),
            generate_content_config=types.GenerateContentConfig(
                tool_config=types.ToolConfig(include_server_side_tool_invocations=True)
            ),
        )
        session_service = InMemorySessionService()
        app_name = "roamstead_live_listings"
        user_id = "live-listing-search"
        session_id = f"search-{uuid4().hex}"
        await session_service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
        runner = Runner(app_name=app_name, agent=agent, session_service=session_service)
        message = types.Content(
            role="user",
            parts=[types.Part(text=_band_prompt(mode, band, target, batch_index, excluded_urls))],
        )

        response_texts: list[str] = []
        grounded_domains: set[str] = set()
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
            if event.content:
                text_parts = [part.text for part in event.content.parts or [] if getattr(part, "text", None)]
                if text_parts:
                    response_texts.append("".join(text_parts))
            metadata = event.grounding_metadata
            if metadata:
                for chunk in metadata.grounding_chunks or []:
                    if chunk.web and chunk.web.domain:
                        grounded_domains.add(chunk.web.domain.lower())

        payload: dict[str, Any] | None = None
        for response_text in reversed(response_texts):
            try:
                payload = _extract_json(response_text)
                break
            except (LiveListingSearchError, json.JSONDecodeError):
                continue
        if payload is None:
            raise LiveListingSearchError("Gemini did not return a JSON listing result.")
        raw_listings = payload.get("listings")
        if not isinstance(raw_listings, list):
            raise LiveListingSearchError("Gemini returned an invalid listings collection.")
        raw_dicts = [item for item in raw_listings if isinstance(item, dict)]
        resolved = await self._resolve_source_urls(raw_dicts)
        enriched = await self._attach_image_urls(resolved)
        normalized = [_normalize(item, mode, grounded_domains) for item in enriched]
        return [item for item in normalized if item is not None and item.price_band == band]

    def get(self, listing_id: str) -> Listing | None:
        for _, listings in self._cache.values():
            match = next((item for item in listings if item.id == listing_id), None)
            if match:
                return match
        return None

    def cached_items(self) -> list[Listing]:
        items: dict[str, Listing] = {}
        for _, listings in self._cache.values():
            items.update({item.id: item for item in listings})
        return list(items.values())


live_listing_search = GeminiLiveListingSearch()
