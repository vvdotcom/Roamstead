from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from .data import CANDIDATES
from .models import (
    DecisionProfile,
    FeedbackEvent,
    HardConstraint,
    Preference,
    PreferenceProposal,
    Session,
)
from .ranking import rank_candidates, weights_from_profile
from .listings.repository import ListingRepository


class MemoryStore:
    """Local golden-demo store. The Firestore adapter is selected in cloud deployments."""

    def __init__(self, persist_profiles: bool = False) -> None:
        self.sessions: dict[str, Session] = {}
        self.profiles: dict[str, DecisionProfile] = {}
        self.proposals: dict[str, PreferenceProposal] = {}
        self.proposal_profiles: dict[str, str] = {}
        self.rankings = {}
        self.saved: dict[str, set[str]] = {}
        self.revisions: dict[str, list[dict]] = {}
        self.profile_repository = ListingRepository() if persist_profiles else None

    def create_session(self, housing_mode: str = "BUY") -> Session:
        session_id = f"session-{uuid4().hex[:8]}"
        profile_id = f"profile-{uuid4().hex[:8]}"
        is_rent = housing_mode == "RENT"
        profile = DecisionProfile(
            profile_id=profile_id,
            hard_constraints=[
                HardConstraint(key="city", label="Ho Chi Minh City", operator="=", value="Ho Chi Minh City"),
                HardConstraint(
                    key="rent_budget" if is_rent else "budget",
                    label="$1,500 monthly rent" if is_rent else "$175k purchase budget",
                    operator="<=",
                    value=1500 if is_rent else 175000,
                ),
                HardConstraint(key="healthcare", label="Hospital within 30 min", operator="<=", value=30),
                HardConstraint(key="min_beds", label="At least 1 bedroom", operator=">=", value=1),
                HardConstraint(key="min_baths", label="At least 1 bathroom", operator=">=", value=1),
                HardConstraint(key="max_international_school_minutes", label="International school within 30 min", operator="<=", value=30),
                HardConstraint(key="max_food_minutes", label="Food and daily needs within 15 min", operator="<=", value=15),
                HardConstraint(
                    key="property_types",
                    label="Apartment or house",
                    operator="in",
                    value="Apartment,House",
                ),
            ],
            preferences=[
                Preference(key="rent" if is_rent else "buy", label="Rent first" if is_rent else "Buy over rent", weight=0.90),
                Preference(key="budget", label="Stay within budget", weight=0.90),
                Preference(key="space", label="Bedrooms and bathrooms", weight=0.65),
                Preference(key="healthcare", label="Healthcare access", weight=0.75),
                Preference(key="remote_work", label="Reliable remote work", weight=0.82),
                Preference(key="waterfront", label="Waterfront access", weight=0.40),
                Preference(key="quiet", label="Quiet neighborhood", weight=0.20),
                Preference(key="international_school", label="International-school access", weight=0.65),
                Preference(key="food_access", label="Food and daily-needs proximity", weight=0.60),
            ],
        )
        session = Session(id=session_id, profile_id=profile_id, housing_mode=housing_mode)
        self.sessions[session_id] = session
        self.profiles[profile_id] = profile
        self.rankings[profile_id] = rank_candidates(CANDIDATES, weights_from_profile(profile))
        self.saved[profile_id] = set()
        self.revisions[profile_id] = []
        self.save_profile(profile)
        self.save_session(session)
        return session

    def save_session(self, session: Session) -> None:
        self.sessions[session.id] = session
        if self.profile_repository:
            self.profile_repository.save_session(session)

    def get_session(self, session_id: str) -> Session | None:
        session = self.sessions.get(session_id)
        if session or not self.profile_repository:
            return session
        session = self.profile_repository.get_session(session_id)
        if session:
            self.sessions[session.id] = session
        return session

    def save_profile(self, profile: DecisionProfile) -> None:
        self._upgrade_profile(profile)
        self.profiles[profile.profile_id] = profile
        if self.profile_repository:
            self.profile_repository.save_profile(profile)

    @staticmethod
    def _upgrade_profile(profile: DecisionProfile) -> bool:
        changed = False
        original_constraints = profile.hard_constraints
        profile.hard_constraints = [item for item in original_constraints if item.key != "min_area_sqm"]
        if len(profile.hard_constraints) != len(original_constraints):
            changed = True

        property_types = next((item for item in profile.hard_constraints if item.key == "property_types"), None)
        if property_types:
            normalized: list[str] = []
            for raw_type in str(property_types.value).split(","):
                name = raw_type.strip().casefold()
                category = "Apartment" if name in {"apartment", "condo", "condominium", "studio", "flat"} else (
                    "House" if name in {"house", "townhouse", "town house", "villa", "shophouse", "shop house", "home"} else None
                )
                if category and category not in normalized:
                    normalized.append(category)
            if not normalized:
                normalized = ["Apartment", "House"]
            normalized_value = ",".join(normalized)
            normalized_label = " and ".join(item.lower() for item in normalized).capitalize()
            if property_types.value != normalized_value or property_types.label != normalized_label:
                property_types.value = normalized_value
                property_types.label = normalized_label
                property_types.operator = "in"
                changed = True
        else:
            profile.hard_constraints.append(HardConstraint(key="property_types", label="Apartment or house", operator="in", value="Apartment,House"))
            changed = True

        original_preferences = profile.preferences
        profile.preferences = [item for item in original_preferences if item.key != "property_type"]
        if len(profile.preferences) != len(original_preferences):
            changed = True
        space_preference = next((item for item in profile.preferences if item.key == "space"), None)
        if space_preference and space_preference.label != "Bedrooms and bathrooms":
            space_preference.label = "Bedrooms and bathrooms"
            changed = True

        constraints = {item.key for item in profile.hard_constraints}
        if "max_international_school_minutes" not in constraints:
            profile.hard_constraints.append(HardConstraint(key="max_international_school_minutes", label="International school within 30 min", operator="<=", value=30))
            changed = True
        if "max_food_minutes" not in constraints:
            profile.hard_constraints.append(HardConstraint(key="max_food_minutes", label="Food and daily needs within 15 min", operator="<=", value=15))
            changed = True
        preferences = {item.key for item in profile.preferences}
        if "international_school" not in preferences:
            profile.preferences.append(Preference(key="international_school", label="International-school access", weight=0.65))
            changed = True
        if "food_access" not in preferences:
            profile.preferences.append(Preference(key="food_access", label="Food and daily-needs proximity", weight=0.60))
            changed = True
        return changed

    def get_profile(self, profile_id: str) -> DecisionProfile | None:
        profile = self.profiles.get(profile_id)
        if profile:
            if self._upgrade_profile(profile):
                self.save_profile(profile)
            return profile
        if not self.profile_repository:
            return None
        profile = self.profile_repository.get_profile(profile_id)
        if profile:
            if self._upgrade_profile(profile):
                self.profile_repository.save_profile(profile)
            self.profiles[profile_id] = profile
            self.rankings[profile_id] = rank_candidates(CANDIDATES, weights_from_profile(profile))
            self.saved.setdefault(profile_id, self.profile_repository.list_saved_items(profile_id))
            self.revisions.setdefault(profile_id, self.profile_repository.list_revisions(profile_id))
        return profile

    def copy_profile(self, profile_id: str) -> DecisionProfile:
        return deepcopy(self.profiles[profile_id])

    def record_feedback(
        self,
        profile_id: str,
        target_id: str,
        action: str,
        reason: str,
        target_name: str | None = None,
        target_type: str = "LISTING",
    ) -> FeedbackEvent:
        if not target_name:
            candidate = next((item for item in CANDIDATES if item.id == target_id), None)
            target_name = candidate.name if candidate else target_id
        event = FeedbackEvent(
            id=f"feedback-{uuid4().hex[:8]}",
            target_id=target_id,
            target_name=target_name,
            target_type=target_type,
            action=action,
            reason=reason,
        )
        profile = self.profiles[profile_id]
        # Idempotency for a repeated click on the same target/action/reason.
        existing = next((item for item in profile.feedback if item.target_id == target_id and item.action == action and item.reason == reason), None)
        if existing:
            return existing
        profile.feedback.append(event)
        if action == "SAVE":
            self.saved[profile_id].add(target_id)
            if self.profile_repository:
                self.profile_repository.save_item(profile_id, target_id)
        return event

    def save_revision(self, profile_id: str, revision: dict) -> None:
        self.revisions.setdefault(profile_id, []).append(revision)
        if self.profile_repository:
            self.profile_repository.save_revision(profile_id, revision)

    def save_proposal(self, profile_id: str, proposal: PreferenceProposal) -> None:
        self.proposals[proposal.id] = proposal
        self.proposal_profiles[proposal.id] = profile_id
        if self.profile_repository:
            self.profile_repository.save_proposal(profile_id, proposal)

    def get_proposal(self, proposal_id: str) -> PreferenceProposal | None:
        proposal = self.proposals.get(proposal_id)
        if proposal:
            return proposal
        if not self.profile_repository:
            return None
        stored = self.profile_repository.get_proposal(proposal_id)
        if not stored:
            return None
        profile_id, proposal = stored
        self.proposals[proposal.id] = proposal
        self.proposal_profiles[proposal.id] = profile_id
        return proposal

    def save_listing(self, profile_id: str, listing_id: str) -> set[str]:
        saved = self.saved.setdefault(
            profile_id,
            self.profile_repository.list_saved_items(profile_id) if self.profile_repository else set(),
        )
        saved.add(listing_id)
        if self.profile_repository:
            self.profile_repository.save_item(profile_id, listing_id)
        return saved


store = MemoryStore(persist_profiles=True)
