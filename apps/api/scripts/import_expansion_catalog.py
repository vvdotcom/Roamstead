"""One-time import of verified Bangkok and Kuala Lumpur listing snapshots.

This utility intentionally has no model dependency. It reads public marketplace
result snapshots, normalizes their source-backed facts, downloads each exact
listing-card photograph, and writes the accepted records to SQLite. Firestore
and Cloud Storage are populated separately by ``seed_cloud_from_local.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.listings.images import cache_listing_image
from app.listings.repository import ListingRepository
from app.models import Listing


PROPERTYHUB_BASE = "https://propertyhub.in.th"
PROPERTYHUB_IMAGE_BASE = "https://bcdn.propertyhub.in.th"
PROPERTYGENIE_BASE = "https://www.propertygenie.com.my"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def price_band(mode: str, usd: int) -> str:
    thresholds = (150_000, 350_000, 750_000) if mode == "BUY" else (700, 1_500, 3_000)
    if usd < thresholds[0]:
        return "LOW"
    if usd < thresholds[1]:
        return "MEDIUM"
    if usd < thresholds[2]:
        return "HIGH"
    return "ULTRA_HIGH"


def stable_id(prefix: str, source_url: str) -> str:
    return f"{prefix}-{hashlib.sha256(source_url.encode()).hexdigest()[:18]}"


async def exchange_rates() -> tuple[dict[str, float], str]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get("https://api.frankfurter.app/latest?from=USD&to=THB,MYR")
        response.raise_for_status()
        payload = response.json()
    return {key: float(value) for key, value in payload["rates"].items()}, str(payload["date"])


def bangkok_items(path: Path, mode: str, rate: float, rate_date: str) -> list[Listing]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    script = soup.select_one("#__NEXT_DATA__")
    if not script or not script.string:
        raise ValueError(f"{path} is not a PropertyHub result snapshot")
    records = json.loads(script.string)["props"]["pageProps"]["resultListings"]
    output: list[Listing] = []
    expected_post_type = "FOR_SALE" if mode == "BUY" else "FOR_RENT"
    for raw in records:
        if raw.get("postType") != expected_post_type or raw.get("propertyType") != "CONDO":
            continue
        room = raw.get("roomInformation") or {}
        beds, baths = room.get("numberOfBed"), room.get("numberOfBath")
        if not isinstance(beds, int) or not isinstance(baths, int) or beds < 1 or baths < 1:
            continue
        local_price = (
            ((raw.get("price") or {}).get("forSale") or {}).get("price")
            if mode == "BUY"
            else ((((raw.get("price") or {}).get("forRent") or {}).get("monthly") or {}).get("price"))
        )
        if not isinstance(local_price, (int, float)) or local_price <= 0:
            continue
        project = raw.get("project") or {}
        district = re.sub(r"\s+Bangkok$", "", str(project.get("address") or "Bangkok")).strip()
        source_url = f"{PROPERTYHUB_BASE}/en/listings/{raw['slug']}---{raw['id']}"
        image_url = f"{PROPERTYHUB_IMAGE_BASE}{raw['coverPicture']}"
        usd = max(1, round(float(local_price) / rate))
        project_name = str(project.get("nameEnglish") or project.get("name") or "Bangkok residence").strip()
        display_title = f"{beds}-Bedroom Apartment at {project_name}"
        output.append(
            Listing(
                id=stable_id("bkk", source_url),
                neighborhood_id="bangkok",
                title=display_title,
                transaction_mode=mode,
                city="Bangkok",
                country="Thailand",
                country_code="TH",
                local_currency="THB",
                price_local=round(float(local_price)),
                price_usd=usd,
                exchange_rate_per_usd=rate,
                exchange_rate_date=rate_date,
                price_band=price_band(mode, usd),
                district=district or "Bangkok",
                address=str(project.get("address") or "Bangkok, Thailand"),
                beds=beds,
                baths=baths,
                area_sqm=float(room["roomArea"]) if room.get("roomArea") else None,
                image_url=image_url,
                image_urls=[image_url],
                property_type="Apartment",
                source_url=source_url,
                source_domain="propertyhub.in.th",
                source_title=str(raw["title"]).strip(),
                source_checked_at=str(raw.get("refreshedAt") or raw.get("updatedAt") or now_iso()),
            )
        )
    return output


def _kl_district(title: str, address: str) -> str:
    combined = f"{title} {address}".casefold()
    for needle, label in (
        ("bukit tunku", "Bukit Tunku"),
        ("klcc", "KL City Centre"),
        ("city centre", "KL City Centre"),
        ("chow kit", "Chow Kit"),
        ("jalan kuching", "Jalan Kuching"),
        ("jalan tun ismail", "Jalan Tun Ismail"),
        ("bukit bintang", "Bukit Bintang"),
    ):
        if needle in combined:
            return label
    return "Kuala Lumpur"


def _kl_display_title(source_title: str) -> str:
    """Remove marketplace promotion copy while preserving the named project."""
    folded = source_title.casefold()
    projects = (
        ("kenny hills residence", "Kenny Hills Residence in Bukit Tunku"),
        ("villa puteri", "Villa Puteri Condominium in Kuala Lumpur City Centre"),
        ("regalia service apartment", "Regalia Service Apartment in Kuala Lumpur"),
        ("the luxe by infinitum", "The Luxe by Infinitum in Kuala Lumpur City Centre"),
        ("kl chamber residence", "Chambers Residence in Chow Kit"),
        ("chambers residence", "Chambers Residence in Chow Kit"),
        ("anggun residence", "Anggun Residences in Kuala Lumpur City Centre"),
        ("villa putra", "Villa Putra Condominium on Jalan Tun Ismail"),
        ("quill residence", "Quill Residence near Kuala Lumpur City Centre"),
        ("sri kenny", "Sri Kenny Residences in Bukit Tunku"),
        ("pavilion suites", "Pavilion Suites in Bukit Bintang"),
        ("jalan ipoh kecil", "Residence on Jalan Ipoh Kecil"),
        ("pavilion kuala lumpur", "Pavilion Residences in Kuala Lumpur City Centre"),
        ("cemerlang villas", "Cemerlang Villas in Bukit Tunku"),
    )
    for needle, display in projects:
        if needle in folded:
            return display
    return re.sub(r"\s+", " ", source_title).strip(" .,-")


def kuala_lumpur_items(path: Path, mode: str, rate: float, rate_date: str) -> list[Listing]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    preferred: list[Listing] = []
    auctions: list[Listing] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="/property/"]'):
        href = str(link.get("href") or "")
        if href in seen:
            continue
        seen.add(href)
        card = link.parent.parent
        title_node = card.select_one("h3")
        image_node = card.select_one("img[src]")
        metric_nodes = card.select("span.text-\\[0\\.85rem\\].font-medium.text-slate-500")
        location_node = card.select_one("span.ml-1\\.5")
        card_text = " ".join(card.get_text(" ", strip=True).split())
        if not title_node or not image_node or len(metric_nodes) < 3:
            continue
        source_title = " ".join(title_node.get_text(" ", strip=True).split())
        if any(word in source_title.casefold() for word in ("office", "hotel", "shop", "commercial land", "bilik sewa")):
            continue
        title = _kl_display_title(source_title)
        try:
            beds = int(metric_nodes[0].get_text(strip=True))
            baths = int(metric_nodes[1].get_text(strip=True))
            area_sqft = float(re.sub(r"[^0-9.]", "", metric_nodes[2].get_text(strip=True)))
            local_price = int(re.search(r"RM\s+([\d,]+)", card_text).group(1).replace(",", ""))  # type: ignore[union-attr]
        except (TypeError, ValueError, AttributeError):
            continue
        if beds < 1 or baths < 1 or area_sqft <= 0 or local_price <= 0:
            continue
        address = location_node.get_text(" ", strip=True) if location_node else "Kuala Lumpur, Malaysia"
        source_url = f"{PROPERTYGENIE_BASE}{href}"
        image_url = str(image_node["src"])
        usd = max(1, round(local_price / rate))
        property_type = "House" if any(word in title.casefold() for word in ("villa", "house", "terrace")) else "Apartment"
        item = Listing(
            id=stable_id("kul", source_url),
            neighborhood_id="kuala-lumpur",
            title=title,
            transaction_mode=mode,
            city="Kuala Lumpur",
            country="Malaysia",
            country_code="MY",
            local_currency="MYR",
            price_local=local_price,
            price_usd=usd,
            exchange_rate_per_usd=rate,
            exchange_rate_date=rate_date,
            price_band=price_band(mode, usd),
            district=_kl_district(title, address),
            address=address,
            beds=beds,
            baths=baths,
            area_sqm=round(area_sqft * 0.092903, 1),
            image_url=image_url,
            image_urls=[image_url],
            property_type=property_type,
            source_url=source_url,
            source_domain="propertygenie.com.my",
            source_title=source_title,
            source_checked_at=now_iso(),
        )
        (auctions if "AUCTION" in card_text else preferred).append(item)
    return preferred + auctions


async def cache_first_ten(items: list[Listing]) -> list[Listing]:
    accepted: list[Listing] = []
    for item in items:
        if await cache_listing_image(item):
            accepted.append(item)
        if len(accepted) == 10:
            break
    return accepted


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=Path("data/roamstead.db"), type=Path)
    parser.add_argument("--bangkok-buy", required=True, type=Path)
    parser.add_argument("--bangkok-rent", required=True, type=Path)
    parser.add_argument("--kl-buy", required=True, type=Path)
    parser.add_argument("--kl-rent", required=True, type=Path)
    args = parser.parse_args()
    rates, rate_date = await exchange_rates()
    batches = {
        ("Bangkok", "BUY"): bangkok_items(args.bangkok_buy, "BUY", rates["THB"], rate_date),
        ("Bangkok", "RENT"): bangkok_items(args.bangkok_rent, "RENT", rates["THB"], rate_date),
        ("Kuala Lumpur", "BUY"): kuala_lumpur_items(args.kl_buy, "BUY", rates["MYR"], rate_date),
        ("Kuala Lumpur", "RENT"): kuala_lumpur_items(args.kl_rent, "RENT", rates["MYR"], rate_date),
    }
    repository = ListingRepository(args.database.resolve())
    for (city, mode), batch in batches.items():
        if len(batch) < 10:
            raise SystemExit(f"{city} {mode} produced {len(batch)} records; refusing a partial import")
        accepted = await cache_first_ten(batch)
        if len(accepted) != 10:
            raise SystemExit(f"{city} {mode} cached {len(accepted)}/10 exact listing photos; database unchanged")
        repository.save_progress(mode, accepted)
        print(f"Stored {len(accepted)} verified {city} {mode} records")


if __name__ == "__main__":
    asyncio.run(main())
