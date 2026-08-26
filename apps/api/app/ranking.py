from copy import deepcopy

from .models import Candidate, DecisionProfile, RankingDelta


INITIAL_WEIGHTS = {
    "budget": 0.30,
    "healthcare": 0.25,
    "remote_work": 0.20,
    "waterfront": 0.20,
    "quiet": 0.05,
    "international_school": 0.15,
    "food_access": 0.10,
}

QUIET_WEIGHTS = {
    "budget": 0.22,
    "healthcare": 0.20,
    "remote_work": 0.12,
    "waterfront": 0.14,
    "quiet": 0.32,
}

SOFT_QUIET_WEIGHTS = {
    "budget": 0.26,
    "healthcare": 0.23,
    "remote_work": 0.16,
    "waterfront": 0.16,
    "quiet": 0.19,
}


def weights_from_profile(profile: DecisionProfile) -> dict[str, float]:
    """Build neighborhood weights from the user's current editable profile."""

    selected = {item.key: item.weight for item in profile.preferences}
    weights = {
        key: max(0.0, selected.get(key, default))
        for key, default in INITIAL_WEIGHTS.items()
    }
    total = sum(weights.values())
    if total <= 0:
        return INITIAL_WEIGHTS.copy()
    return {key: value / total for key, value in weights.items()}


def rank_candidates(candidates: list[Candidate], weights: dict[str, float]) -> list[Candidate]:
    ranked = deepcopy(candidates)
    for item in ranked:
        values = item.components.model_dump()
        item.score = round(sum(values[key] * weight for key, weight in weights.items()))
    ranked.sort(key=lambda item: (-item.score, item.name))
    for index, item in enumerate(ranked, start=1):
        item.rank = index
    return ranked


def ranking_deltas(before: list[Candidate], after: list[Candidate]) -> list[RankingDelta]:
    previous = {item.id: item for item in before}
    return [
        RankingDelta(
            candidate_id=item.id,
            name=item.name,
            previous_rank=previous[item.id].rank,
            new_rank=item.rank,
            previous_score=previous[item.id].score,
            new_score=item.score,
        )
        for item in after
    ]
