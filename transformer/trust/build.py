"""Build trust artifacts (explain / report / gating) from resolved Profiles."""

from __future__ import annotations

from typing import List

from ..model import Profile
from ..projection.paths import resolve_path
from . import anomalies

# Fields that constitute a "complete" profile, for the completeness score.
CORE_FIELDS = [
    "full_name", "emails", "phones", "location.country", "headline",
    "years_experience", "skills", "experience", "education",
]

DEFAULT_THRESHOLD = 0.6


def _populated(root: dict, path: str) -> bool:
    found, value = resolve_path(root, path)
    if not found or value is None:
        return False
    if isinstance(value, (list, str, dict)) and len(value) == 0:
        return False
    return True


def completeness(profile: Profile) -> float:
    root = profile.to_dict()
    hits = sum(1 for f in CORE_FIELDS if _populated(root, f))
    return round(hits / len(CORE_FIELDS), 4)


def explain(profile: Profile) -> dict:
    """The per-field audit trail: winner, the alternatives it beat, and why."""
    return profile.trace


def quality_report(profile: Profile, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Per-candidate data-quality + conflict report with a review verdict."""
    comp = completeness(profile)

    conflicts = []
    for field, dec in profile.trace.items():
        if dec and dec.get("conflict"):
            alts = [
                {"value": c["value"], "source": c["source"]}
                for c in dec.get("considered", []) if not c.get("won")
            ]
            conflicts.append({"field": field, "chosen": dec.get("chosen"), "alternatives": alts})

    low_conf = [
        {"field": f, "confidence": c}
        for f, c in sorted(profile.field_confidence.items())
        if c < threshold
    ]

    anomaly_list = anomalies.detect(profile)

    flags = []
    if not profile.emails:
        flags.append("no_email")
    if not profile.phones:
        flags.append("no_phone")
    if not profile.skills:
        flags.append("no_skills")
    if comp < 0.5:
        flags.append("sparse")
    if anomaly_list:
        flags.append("anomaly")

    # Review gating: explicit, explainable reasons.
    reasons = []
    if "no_email" in flags:
        reasons.append("no email address resolved")
    if profile.overall_confidence < threshold:
        reasons.append(f"overall_confidence {profile.overall_confidence} < {threshold}")
    if comp < 0.5:
        reasons.append(f"completeness {comp} < 0.5")
    for a in anomaly_list:
        reasons.append(f"anomaly: {a['type']} ({a['detail']})")

    return {
        "candidate_id": profile.candidate_id,
        "overall_confidence": profile.overall_confidence,
        "completeness": comp,
        "conflicts": conflicts,
        "low_confidence_fields": low_conf,
        "anomalies": anomaly_list,
        "flags": flags,
        "needs_review": bool(reasons),
        "review_reasons": reasons,
    }


def build_trust(profiles: List[Profile], threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Full trust bundle: per-candidate report + explain trace, and a batch rollup."""
    candidates = []
    conflict_counts: dict = {}
    review_queue = []
    anomaly_total = 0
    conf_sum = 0.0
    comp_sum = 0.0

    for p in profiles:
        report = quality_report(p, threshold)
        report["explain"] = explain(p)
        candidates.append(report)
        conf_sum += p.overall_confidence
        comp_sum += report["completeness"]
        anomaly_total += len(report["anomalies"])
        for c in report["conflicts"]:
            conflict_counts[c["field"]] = conflict_counts.get(c["field"], 0) + 1
        if report["needs_review"]:
            review_queue.append(p.candidate_id)

    n = len(profiles) or 1
    batch = {
        "total": len(profiles),
        "accepted": len(profiles) - len(review_queue),
        "needs_review": len(review_queue),
        "anomalies": anomaly_total,
        "avg_confidence": round(conf_sum / n, 4),
        "avg_completeness": round(comp_sum / n, 4),
        "conflict_field_counts": dict(sorted(conflict_counts.items(), key=lambda kv: -kv[1])),
        "review_queue": review_queue,
    }
    return {"threshold": threshold, "batch": batch, "candidates": candidates}
