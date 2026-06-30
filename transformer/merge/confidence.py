"""Deterministic confidence model.

Confidence is a fixed function of *who* said it and *how* it was extracted, with a
bump for corroboration and a penalty for conflict. No randomness, no time, no
network -- the same inputs always yield the same numbers, which is what makes the
output explainable and reproducible.
"""

from __future__ import annotations

from ..model import (
    SOURCE_OVERRIDE, SOURCE_ATS_JSON, SOURCE_RECRUITER_CSV, SOURCE_GITHUB,
    SOURCE_RECRUITER_NOTES, SOURCE_RESUME,
    METHOD_FIELD_MAP, METHOD_API, METHOD_REGEX, METHOD_HUMAN,
)

# How much we trust each source's curation. A human correction is trusted above
# everything; recruiter-curated structured data next; free-text notes least.
SOURCE_WEIGHT = {
    SOURCE_OVERRIDE: 1.00,
    SOURCE_ATS_JSON: 0.90,
    SOURCE_RECRUITER_CSV: 0.85,
    SOURCE_GITHUB: 0.75,
    SOURCE_RESUME: 0.55,
    SOURCE_RECRUITER_NOTES: 0.50,
}

# How much we trust the extraction method itself.
METHOD_CERTAINTY = {
    METHOD_HUMAN: 1.00,
    METHOD_FIELD_MAP: 1.00,
    METHOD_API: 0.95,
    METHOD_REGEX: 0.70,
}

CONFLICT_PENALTY = 0.85   # multiplier when sources disagreed on the winner
AGREEMENT_BONUS = 0.07    # added per corroborating source beyond the first


def base_confidence(source: str, method: str, weights: dict = None) -> float:
    """Base confidence = source weight x method certainty.

    ``weights`` optionally overrides the static SOURCE_WEIGHT per source -- this is
    how the self-calibrating trust layer feeds learned reliabilities back into the
    engine without touching the static defaults.
    """
    w = SOURCE_WEIGHT.get(source, 0.4)
    if weights and source in weights:
        w = weights[source]
    return round(w * METHOD_CERTAINTY.get(method, 0.6), 4)


def adjusted(base: float, agree_count: int, had_conflict: bool) -> float:
    """Apply corroboration bonus and conflict penalty, clamped to [0, 1]."""
    score = base + AGREEMENT_BONUS * max(0, agree_count - 1)
    if had_conflict:
        score *= CONFLICT_PENALTY
    return round(max(0.0, min(1.0, score)), 4)
