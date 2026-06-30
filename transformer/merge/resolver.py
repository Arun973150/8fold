"""Cluster source records into candidates and resolve each cluster into one
canonical Profile.

Clustering: records are the same person if they share a normalized email or a
normalized full name (union-find). This is intentionally conservative -- we do not
fuzzily merge different names, and that limitation is documented.

Resolution: scalar fields pick a reliability-weighted winner (every contributing
source is still recorded in provenance); list fields are unioned and deduped;
skills are canonicalized and corroboration-ranked. Nothing is invented.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..model import Profile, SourceRecord
from ..normalize.emails import normalize_emails
from ..normalize.phones import normalize_phones
from ..normalize.skills import normalize_skill
from ..normalize.location import normalize_location, normalize_country
from ..normalize.dates import normalize_date, normalize_year
from . import confidence as conf

# Deterministic tie-break order (descending trust). A human override outranks all.
_PRIORITY = ["recruiter_override", "ats_json", "recruiter_csv", "github", "resume", "recruiter_notes"]


def _prio(source: str) -> int:
    return _PRIORITY.index(source) if source in _PRIORITY else len(_PRIORITY)


# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #
def _identity_keys(rec: SourceRecord) -> Tuple[set, Optional[str]]:
    emails = set(normalize_emails(rec.raw.get("emails")))
    name = rec.raw.get("full_name")
    name_key = name.strip().lower() if isinstance(name, str) and name.strip() else None
    return emails, name_key


def cluster(records: List[SourceRecord]) -> List[List[SourceRecord]]:
    n = len(records)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    keys = [_identity_keys(r) for r in records]
    # Link records that share an email or a name.
    by_email: dict = {}
    by_name: dict = {}
    for i, (emails, name_key) in enumerate(keys):
        for e in emails:
            if e in by_email:
                union(i, by_email[e])
            else:
                by_email[e] = i
        if name_key:
            if name_key in by_name:
                union(i, by_name[name_key])
            else:
                by_name[name_key] = i

    groups: dict = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(records[i])
    # Stable ordering by first source priority then insertion.
    return list(groups.values())


# --------------------------------------------------------------------------- #
# Field resolution helpers
# --------------------------------------------------------------------------- #
def _scalar_candidates(records, field, transform=lambda x: x):
    """Yield (value, source, method) for each record that has a usable value."""
    out = []
    for rec in records:
        if field not in rec.raw:
            continue
        val = transform(rec.raw[field])
        if val is None or val == "":
            continue
        out.append((val, rec.source, rec.method_for(field)))
    return out


def _resolve_scalar(records, field, transform=lambda x: x, weights=None):
    """Return (winner_value, confidence, provenance_entries, decision).

    ``decision`` is the trust-layer audit record: the chosen value plus EVERY
    proposal that was considered (winners and losers), whether a conflict fired,
    and a human-readable reason. ``weights`` carries calibrated source weights.
    """
    cands = _scalar_candidates(records, field, transform)
    if not cands:
        return None, 0.0, [], None
    # Winner: highest base confidence, tie-broken by source priority.
    cands_sorted = sorted(
        cands,
        key=lambda c: (-conf.base_confidence(c[1], c[2], weights), _prio(c[1])),
    )
    winner_value, winner_source, winner_method = cands_sorted[0]
    distinct = {c[0] for c in cands}
    had_conflict = len(distinct) > 1
    agree = sum(1 for c in cands if c[0] == winner_value)
    base = conf.base_confidence(winner_source, winner_method, weights)
    confidence = conf.adjusted(base, agree, had_conflict)
    provenance = [{"field": field, "source": s, "method": m} for (_, s, m) in cands]

    considered = [
        {
            "value": v, "source": s, "method": m,
            "base": conf.base_confidence(s, m, weights),
            "won": (v == winner_value and s == winner_source and m == winner_method),
        }
        for (v, s, m) in cands_sorted
    ]
    if had_conflict:
        reason = (
            f"chosen from {winner_source} (base {base}) over "
            f"{len(distinct) - 1} differing value(s); sources conflicted -> "
            f"confidence penalized"
        )
    else:
        reason = (
            f"chosen from {winner_source} (base {base}); "
            f"{agree} source(s) agreed -> corroboration bonus"
            if agree > 1 else f"single source {winner_source} (base {base})"
        )
    decision = {
        "field": field, "chosen": winner_value, "confidence": confidence,
        "conflict": had_conflict, "considered": considered, "reason": reason,
    }
    return winner_value, confidence, provenance, decision


def _clean_str(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


# --------------------------------------------------------------------------- #
# Main resolve
# --------------------------------------------------------------------------- #
def resolve(records: List[SourceRecord], candidate_id: str, weights: dict = None) -> Profile:
    profile = Profile(candidate_id=candidate_id)
    provenance: List[dict] = []
    field_conf: dict = {}
    trace: dict = {}

    # ---- scalar identity fields ----
    name, c, prov, dec = _resolve_scalar(records, "full_name", _clean_str, weights)
    if name is not None:
        profile.full_name = name
        field_conf["full_name"] = c
        provenance += prov
        trace["full_name"] = dec

    headline, c, prov, dec = _resolve_scalar(records, "headline", _clean_str, weights)
    if headline is not None:
        profile.headline = headline
        field_conf["headline"] = c
        provenance += prov
        trace["headline"] = dec

    yrs, c, prov, dec = _resolve_scalar(
        records, "years_experience",
        lambda v: float(v) if isinstance(v, (int, float)) else None,
        weights,
    )
    if yrs is not None:
        profile.years_experience = yrs
        field_conf["years_experience"] = c
        provenance += prov
        trace["years_experience"] = dec

    # ---- list fields: emails / phones ----
    emails, ec, eprov, edec = _resolve_list(records, "emails", normalize_emails, weights)
    profile.emails = emails
    if emails:
        field_conf["emails"] = ec
        provenance += eprov
        trace["emails"] = edec

    phones, pc, pprov, pdec = _resolve_list(records, "phones", normalize_phones, weights)
    profile.phones = phones
    if phones:
        field_conf["phones"] = pc
        provenance += pprov
        trace["phones"] = pdec

    # ---- location (field-wise best source) ----
    profile.location, loc_prov, loc_c = _resolve_location(records, weights)
    if loc_c:
        field_conf["location"] = loc_c
        provenance += loc_prov

    # ---- links ----
    profile.links, link_prov = _resolve_links(records)
    provenance += link_prov

    # ---- skills ----
    profile.skills, skill_prov, skill_c = _resolve_skills(records, weights)
    if profile.skills:
        field_conf["skills"] = skill_c
        provenance += skill_prov
        trace["skills"] = {
            "field": "skills", "confidence": skill_c, "conflict": False,
            "considered": [
                {"value": s["name"], "sources": s["sources"], "confidence": s["confidence"]}
                for s in profile.skills
            ],
            "reason": f"{len(profile.skills)} skill(s) canonicalized and corroboration-ranked",
        }

    # ---- experience / education ----
    profile.experience, exp_prov = _resolve_experience(records)
    provenance += exp_prov
    profile.education, edu_prov = _resolve_education(records)
    provenance += edu_prov

    profile.provenance = provenance
    profile.field_confidence = field_conf
    profile.trace = trace
    # Overall = mean of per-field confidences actually populated.
    if field_conf:
        profile.overall_confidence = round(sum(field_conf.values()) / len(field_conf), 4)
    return profile


def _resolve_list(records, field, normalize_many, weights=None):
    values: List[str] = []
    contributors = []
    considered = []
    dropped = 0
    for rec in records:
        if field not in rec.raw:
            continue
        raw_vals = rec.raw[field]
        raw_count = len(raw_vals) if isinstance(raw_vals, list) else 1
        norm = normalize_many(raw_vals)
        if not norm:
            dropped += raw_count  # everything this source offered was garbage
            continue
        dropped += max(0, raw_count - len(norm))
        contributors.append((rec.source, rec.method_for(field)))
        considered.append({"source": rec.source, "method": rec.method_for(field), "values": norm})
        for v in norm:
            if v not in values:
                values.append(v)
    if not values:
        return [], 0.0, [], None
    best_base = max(conf.base_confidence(s, m, weights) for (s, m) in contributors)
    confidence = conf.adjusted(best_base, len(contributors), had_conflict=False)
    prov = [{"field": field, "source": s, "method": m} for (s, m) in contributors]
    reason = f"union of {len(contributors)} source(s), deduped to {len(values)} value(s)"
    if dropped:
        reason += f"; {dropped} unparseable value(s) dropped"
    decision = {
        "field": field, "chosen": values, "confidence": confidence,
        "conflict": False, "considered": considered, "reason": reason,
    }
    return values, confidence, prov, decision


def _resolve_location(records, weights=None):
    parts = {"city": None, "region": None, "country": None}
    prov = []
    best_conf = 0.0
    # Highest-priority source wins each sub-field it can fill.
    ranked = sorted(records, key=lambda r: _prio(r.source))
    for rec in ranked:
        if "location" not in rec.raw:
            continue
        norm = normalize_location(rec.raw["location"])
        contributed = False
        for k in ("city", "region", "country"):
            if parts[k] is None and norm.get(k):
                parts[k] = norm[k]
                contributed = True
        if contributed:
            prov.append({"field": "location", "source": rec.source, "method": rec.method_for("location")})
            best_conf = max(best_conf, conf.base_confidence(rec.source, rec.method_for("location"), weights))
    return parts, prov, round(best_conf, 4)


def _resolve_links(records):
    links = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    prov = []
    ranked = sorted(records, key=lambda r: _prio(r.source))
    for rec in ranked:
        raw_links = rec.raw.get("links")
        if not isinstance(raw_links, dict):
            continue
        contributed = False
        for k in ("linkedin", "github", "portfolio"):
            if links[k] is None and raw_links.get(k):
                links[k] = raw_links[k]
                contributed = True
        for o in raw_links.get("other", []) or []:
            if o and o not in links["other"]:
                links["other"].append(o)
                contributed = True
        if contributed:
            prov.append({"field": "links", "source": rec.source, "method": rec.method_for("links")})
    return links, prov


def _resolve_skills(records, weights=None):
    # canonical name -> set of sources, best base confidence
    agg: dict = {}
    for rec in records:
        raw_skills = rec.raw.get("skills")
        if not isinstance(raw_skills, list):
            continue
        method = rec.method_for("skills")
        for s in raw_skills:
            canon = normalize_skill(s)
            if not canon:
                continue
            entry = agg.setdefault(canon, {"sources": [], "base": 0.0})
            if rec.source not in entry["sources"]:
                entry["sources"].append(rec.source)
            entry["base"] = max(entry["base"], conf.base_confidence(rec.source, method, weights))
    skills = []
    prov = []
    best_conf = 0.0
    for name in sorted(agg.keys()):
        entry = agg[name]
        c = conf.adjusted(entry["base"], len(entry["sources"]), had_conflict=False)
        skills.append({"name": name, "confidence": c, "sources": entry["sources"]})
        best_conf = max(best_conf, c)
    if skills:
        # one provenance line per source that contributed any skill
        srcs = {s for e in agg.values() for s in e["sources"]}
        for rec in records:
            if rec.source in srcs and isinstance(rec.raw.get("skills"), list):
                prov.append({"field": "skills", "source": rec.source, "method": rec.method_for("skills")})
    return skills, prov, round(best_conf, 4)


def _norm_exp_entry(e):
    if not isinstance(e, dict):
        return None
    return {
        "company": _clean_str(e.get("company")),
        "title": _clean_str(e.get("title")),
        "start": normalize_date(e.get("start")),
        "end": normalize_date(e.get("end")),
        "summary": _clean_str(e.get("summary")),
    }


def _resolve_experience(records):
    out = []
    seen = set()
    prov = []
    for rec in sorted(records, key=lambda r: _prio(r.source)):
        exp = rec.raw.get("experience")
        if not isinstance(exp, list):
            continue
        contributed = False
        for e in exp:
            ne = _norm_exp_entry(e)
            if ne is None or (ne["company"] is None and ne["title"] is None):
                continue
            key = ((ne["company"] or "").lower(), (ne["title"] or "").lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(ne)
            contributed = True
        if contributed:
            prov.append({"field": "experience", "source": rec.source, "method": rec.method_for("experience")})
    return out, prov


def _resolve_education(records):
    out = []
    seen = set()
    prov = []
    for rec in sorted(records, key=lambda r: _prio(r.source)):
        edu = rec.raw.get("education")
        if not isinstance(edu, list):
            continue
        contributed = False
        for e in edu:
            if not isinstance(e, dict):
                continue
            entry = {
                "institution": _clean_str(e.get("institution")),
                "degree": _clean_str(e.get("degree")),
                "field": _clean_str(e.get("field")),
                "end_year": normalize_year(e.get("end_year")),
            }
            if entry["institution"] is None and entry["degree"] is None:
                continue
            key = ((entry["institution"] or "").lower(), (entry["degree"] or "").lower(), (entry["field"] or "").lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
            contributed = True
        if contributed:
            prov.append({"field": "education", "source": rec.source, "method": rec.method_for("education")})
    return out, prov
