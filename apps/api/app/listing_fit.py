from __future__ import annotations

from statistics import mean

from .models import Candidate, DecisionProfile, Listing


FIT_KEYS = ("budget", "space", "healthcare", "remote_work", "waterfront", "quiet", "international_school", "food_access")
FIT_LABELS = {
    "budget": "Budget",
    "space": "Bedrooms and bathrooms",
    "healthcare": "Healthcare access",
    "remote_work": "Remote-work readiness",
    "waterfront": "Waterfront access",
    "quiet": "Quiet surroundings",
    "international_school": "International-school access",
    "food_access": "Food and daily-needs proximity",
}


def _constraint(profile: DecisionProfile, key: str) -> str | int | float | bool | None:
    item = next((entry for entry in profile.hard_constraints if entry.key == key), None)
    return item.value if item else None


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _budget_limit(profile: DecisionProfile, mode: str) -> int | None:
    return _positive_int(_constraint(profile, "rent_budget" if mode == "RENT" else "budget"))


def _budget_score(price_usd: int, limit_usd: int | None) -> int:
    if not limit_usd:
        return 70
    ratio = price_usd / limit_usd
    if ratio <= 1:
        return round(100 - (ratio * 10))
    return max(0, round(90 - ((ratio - 1) * 90)))


def _property_category(value: str) -> str | None:
    normalized = value.casefold().replace("-", " ")
    if any(term in normalized for term in ("apartment", "condo", "studio", "flat")):
        return "Apartment"
    if any(term in normalized for term in ("house", "home", "townhome", "villa")):
        return "House"
    return None


def _preferred_property_types(profile: DecisionProfile) -> set[str]:
    raw = _constraint(profile, "property_types")
    if not isinstance(raw, str):
        return set()
    return {category for item in raw.split(",") if (category := _property_category(item))}


def _matches_property_type(listing: Listing, profile: DecisionProfile) -> bool:
    preferred = _preferred_property_types(profile)
    if not preferred:
        return True
    return _property_category(listing.property_type) in preferred


def _hard_constraint_failure(listing: Listing, profile: DecisionProfile) -> str | None:
    if not _matches_property_type(listing, profile):
        return "Does not match your selected property type"

    budget_limit = _budget_limit(profile, listing.transaction_mode)
    if budget_limit and listing.price_usd > budget_limit:
        return f"Exceeds your {budget_limit:,} USD budget"

    minimum_beds = _positive_int(_constraint(profile, "min_beds"))
    if minimum_beds and (listing.beds is None or listing.beds < minimum_beds):
        return f"Does not confirm at least {minimum_beds} bedroom{'s' if minimum_beds != 1 else ''}"

    minimum_baths = _positive_int(_constraint(profile, "min_baths"))
    if minimum_baths and (listing.baths is None or listing.baths < minimum_baths):
        return f"Does not confirm at least {minimum_baths} bathroom{'s' if minimum_baths != 1 else ''}"
    return None


def _minimum_score(actual: float | int | None, minimum: int | None) -> int | None:
    if not minimum:
        return None
    if actual is None:
        return 60
    if actual >= minimum:
        return 100
    return max(10, round((actual / minimum) * 85))


def _space_score(listing: Listing, profile: DecisionProfile) -> int:
    scores = [
        _minimum_score(listing.beds, _positive_int(_constraint(profile, "min_beds"))),
        _minimum_score(listing.baths, _positive_int(_constraint(profile, "min_baths"))),
    ]
    known = [score for score in scores if score is not None]
    return round(mean(known)) if known else 70


def _listing_neighborhood(listing: Listing, neighborhoods: list[Candidate]) -> Candidate | None:
    direct = next((item for item in neighborhoods if item.id == listing.neighborhood_id), None)
    if direct:
        return direct
    district = listing.district.casefold()
    return next((item for item in neighborhoods if item.district.casefold() == district), None)


def _neighborhood_component(key: str, neighborhood: Candidate | None, neighborhoods: list[Candidate]) -> int:
    if neighborhood:
        return int(getattr(neighborhood.components, key))
    if neighborhoods:
        return round(mean(int(getattr(item.components, key)) for item in neighborhoods))
    return 70


def _proximity_score(minutes: int | None, maximum: int | None) -> int:
    if minutes is None or maximum is None:
        return 65
    if minutes <= maximum:
        return max(85, round(100 - (minutes / maximum) * 12))
    return max(15, round(85 - ((minutes - maximum) / maximum) * 70))


def _estimated_minutes(key: str, neighborhood: Candidate | None, neighborhoods: list[Candidate]) -> int | None:
    if neighborhood:
        return int(getattr(neighborhood, key))
    if neighborhoods:
        return round(mean(int(getattr(item, key)) for item in neighborhoods))
    return None


def _priority_weights(profile: DecisionProfile) -> dict[str, float]:
    selected = {item.key: item.weight for item in profile.preferences}
    defaults = {
        "budget": 0.90,
        "space": 0.65,
        "healthcare": 0.75,
        "remote_work": 0.82,
        "waterfront": 0.40,
        "quiet": 0.50,
        "international_school": 0.65,
        "food_access": 0.60,
    }
    return {key: max(0.0, selected.get(key, defaults[key])) for key in FIT_KEYS}


def listing_fit_details(
    listing: Listing,
    profile: DecisionProfile,
    neighborhoods: list[Candidate],
    focused_neighborhood_id: str | None = None,
) -> tuple[int, dict[str, int], list[str]]:
    """Calculate an explainable profile-specific score and factor breakdown."""

    hard_constraint_failure = _hard_constraint_failure(listing, profile)
    if hard_constraint_failure:
        return 0, {}, [hard_constraint_failure]

    budget_limit = _budget_limit(profile, listing.transaction_mode)
    neighborhood = _listing_neighborhood(listing, neighborhoods)
    school_minutes = _estimated_minutes("international_school_minutes", neighborhood, neighborhoods)
    food_minutes = _estimated_minutes("food_minutes", neighborhood, neighborhoods)
    breakdown = {
        "budget": _budget_score(listing.price_usd, budget_limit),
        "space": _space_score(listing, profile),
        "healthcare": _neighborhood_component("healthcare", neighborhood, neighborhoods),
        "remote_work": _neighborhood_component("remote_work", neighborhood, neighborhoods),
        "waterfront": _neighborhood_component("waterfront", neighborhood, neighborhoods),
        "quiet": _neighborhood_component("quiet", neighborhood, neighborhoods),
        "international_school": round(mean((
            _neighborhood_component("international_school", neighborhood, neighborhoods),
            _proximity_score(school_minutes, _positive_int(_constraint(profile, "max_international_school_minutes"))),
        ))),
        "food_access": round(mean((
            _neighborhood_component("food_access", neighborhood, neighborhoods),
            _proximity_score(food_minutes, _positive_int(_constraint(profile, "max_food_minutes"))),
        ))),
    }
    weights = _priority_weights(profile)
    total_weight = sum(weights.values()) or 1
    score = round(sum(breakdown[key] * weights[key] for key in FIT_KEYS) / total_weight)

    if neighborhood and focused_neighborhood_id == neighborhood.id:
        score += 3

    rejected_ids = {event.target_id for event in profile.feedback if event.action == "REJECT"}
    if neighborhood and neighborhood.id in rejected_ids:
        score -= 12

    reasons: list[str] = []
    if budget_limit:
        reasons.append(f"Within your {budget_limit:,} USD budget")
    category = _property_category(listing.property_type)
    if category:
        reasons.append(f"Matches your {category.lower()} preference")
    if breakdown["space"] >= 90:
        reasons.append("Meets your bedroom and bathroom targets")

    lifestyle_keys = ("healthcare", "remote_work", "waterfront", "quiet", "international_school", "food_access")
    top_lifestyle = max(lifestyle_keys, key=lambda key: weights[key])
    if top_lifestyle == "international_school" and school_minutes is not None:
        reasons.append(f"About {school_minutes} min to international-school options (district estimate)")
    elif top_lifestyle == "food_access" and food_minutes is not None:
        reasons.append(f"About {food_minutes} min to food and daily needs (district estimate)")
    else:
        reasons.append(f"{FIT_LABELS[top_lifestyle]}: {breakdown[top_lifestyle]}/100")
    return max(0, min(100, score)), breakdown, reasons[:3]


def score_listing_fit(
    listing: Listing,
    profile: DecisionProfile,
    neighborhoods: list[Candidate],
    focused_neighborhood_id: str | None = None,
) -> int:
    return listing_fit_details(listing, profile, neighborhoods, focused_neighborhood_id)[0]


def score_listing_results(
    listings: list[Listing],
    profile: DecisionProfile,
    neighborhoods: list[Candidate],
    focused_neighborhood_id: str | None = None,
) -> list[Listing]:
    scored: list[Listing] = []
    for item in listings:
        if _hard_constraint_failure(item, profile):
            continue
        fit_score, fit_breakdown, fit_reasons = listing_fit_details(
            item,
            profile,
            neighborhoods,
            focused_neighborhood_id,
        )
        scored.append(
            item.model_copy(
                deep=True,
                update={
                    "property_type": _property_category(item.property_type) or item.property_type,
                    "fit_score": fit_score,
                    "fit_breakdown": fit_breakdown,
                    "fit_reasons": fit_reasons,
                    "international_school_minutes_estimate": _estimated_minutes(
                        "international_school_minutes", _listing_neighborhood(item, neighborhoods), neighborhoods
                    ),
                    "food_minutes_estimate": _estimated_minutes(
                        "food_minutes", _listing_neighborhood(item, neighborhoods), neighborhoods
                    ),
                },
            )
        )
    return sorted(scored, key=lambda item: (-item.fit_score, item.price_usd, item.title))
