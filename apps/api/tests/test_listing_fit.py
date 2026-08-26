from app.data import CANDIDATES
from app.listing_fit import score_listing_fit, score_listing_results
from app.models import Listing
from app.ranking import INITIAL_WEIGHTS, rank_candidates, weights_from_profile
from app.store import MemoryStore


def make_listing(
    price_usd: int,
    neighborhood_id: str = "nha-be",
    property_type: str = "Apartment",
    beds: int | None = 2,
    baths: int | None = 2,
) -> Listing:
    return Listing(
        id=f"listing-{price_usd}-{neighborhood_id}",
        neighborhood_id=neighborhood_id,
        title="English property title",
        transaction_mode="BUY",
        price_vnd=price_usd * 26_000,
        price_usd=price_usd,
        price_band="MEDIUM",
        district="Nha Be District",
        beds=beds,
        baths=baths,
        image_url="https://cdn.batdongsan.com.vn/property.jpg",
        property_type=property_type,
        source_url=f"https://batdongsan.com.vn/property-{price_usd}",
        demo=False,
    )


def test_fit_score_rejects_properties_over_the_profile_budget():
    memory = MemoryStore()
    session = memory.create_session("BUY")
    profile = memory.profiles[session.profile_id]
    neighborhoods = memory.rankings[session.profile_id]

    within_budget = score_listing_fit(make_listing(140_000), profile, neighborhoods)
    over_budget = score_listing_fit(make_listing(220_000), profile, neighborhoods)

    assert 0 < within_budget <= 100
    assert over_budget == 0


def test_confirmed_quiet_preference_changes_listing_fit_and_results_are_sorted():
    memory = MemoryStore()
    session = memory.create_session("BUY")
    profile = memory.profiles[session.profile_id]
    urban_listing = make_listing(140_000, "thu-thiem")

    initial = score_listing_fit(urban_listing, profile, rank_candidates(CANDIDATES, weights_from_profile(profile)))
    next(item for item in profile.preferences if item.key == "quiet").weight = 1
    quiet_rankings = rank_candidates(CANDIDATES, weights_from_profile(profile))
    quiet = score_listing_fit(urban_listing, profile, quiet_rankings)
    scored = score_listing_results(
        [make_listing(220_000, "hcmc"), urban_listing],
        profile,
        quiet_rankings,
        "nha-be",
    )

    assert quiet < initial
    assert scored[0].id == urban_listing.id
    assert all(item.fit_score > 0 for item in scored)


def test_property_type_is_a_hard_filter_and_townhouses_are_grouped_as_houses():
    memory = MemoryStore()
    session = memory.create_session("BUY")
    profile = memory.profiles[session.profile_id]
    property_types = next(item for item in profile.hard_constraints if item.key == "property_types")
    property_types.value = "House"
    property_types.label = "House"

    scored = score_listing_results(
        [
            make_listing(140_000, property_type="Apartment"),
            make_listing(145_000, property_type="Townhouse"),
            make_listing(150_000, property_type="Villa"),
        ],
        profile,
        memory.rankings[session.profile_id],
    )

    assert len(scored) == 2
    assert {item.property_type for item in scored} == {"House"}
    assert all("Matches your house preference" in item.fit_reasons for item in scored)


def test_budget_bedroom_and_bathroom_requirements_filter_results():
    memory = MemoryStore()
    session = memory.create_session("BUY")
    profile = memory.profiles[session.profile_id]
    next(item for item in profile.hard_constraints if item.key == "min_beds").value = 2
    next(item for item in profile.hard_constraints if item.key == "min_baths").value = 2

    eligible = make_listing(160_000, beds=2, baths=2)
    scored = score_listing_results(
        [
            eligible,
            make_listing(180_000, beds=3, baths=3),
            make_listing(150_000, beds=1, baths=2),
            make_listing(150_000, beds=2, baths=1),
            make_listing(150_000, beds=None, baths=2),
            make_listing(150_000, beds=2, baths=None),
        ],
        profile,
        memory.rankings[session.profile_id],
    )

    assert [item.id for item in scored] == [eligible.id]
