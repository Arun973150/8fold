"""ATS JSON blob adapter (structured source).

The ATS uses its OWN field vocabulary that does not match ours. The mapping table
below is the explicit translation layer required by the assignment -- every ATS
key we understand is listed here, so the mapping is auditable rather than implicit.
Unknown ATS keys are ignored (never invented into our schema).
"""

from __future__ import annotations

import json
from typing import List

from ..model import SourceRecord, SOURCE_ATS_JSON, METHOD_FIELD_MAP


def _clean(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _map_candidate(c: dict) -> dict:
    """Translate one ATS candidate object into a canonical-keyed raw dict."""
    raw = {}

    name = _clean(c.get("applicant_name") or c.get("full_name"))
    if name:
        raw["full_name"] = name

    contact = c.get("contact") or {}
    email = _clean(contact.get("email_address") or c.get("email"))
    if email:
        raw["emails"] = [email]
    phone = _clean(contact.get("mobile") or contact.get("phone"))
    if phone:
        raw["phones"] = [phone]

    # Location split across ATS keys.
    loc = {
        "city": _clean(c.get("city")),
        "state": _clean(c.get("state")),
        "country": _clean(c.get("country")),
    }
    if any(loc.values()):
        raw["location"] = loc

    headline = _clean(c.get("job_title"))
    if headline:
        raw["headline"] = headline

    yrs = c.get("experience_years")
    if isinstance(yrs, (int, float)):
        raw["years_experience"] = float(yrs)

    # Skills live under "tags" in this ATS.
    tags = c.get("tags") or c.get("skills")
    if isinstance(tags, list) and tags:
        raw["skills"] = [t for t in tags if isinstance(t, str)]

    # GitHub handle, if the ATS happens to store it -- feeds live enrichment.
    gh = _clean(c.get("github") or c.get("github_username"))
    if gh:
        raw["links"] = {"github": gh}

    # Work history -> experience.
    wh = c.get("work_history")
    if isinstance(wh, list) and wh:
        exp = []
        for w in wh:
            if not isinstance(w, dict):
                continue
            exp.append({
                "company": _clean(w.get("org") or w.get("company")),
                "title": _clean(w.get("role") or w.get("title")),
                "start": w.get("from") or w.get("start"),
                "end": w.get("to") or w.get("end"),
                "summary": _clean(w.get("summary")),
            })
        if exp:
            raw["experience"] = exp

    # Schools -> education.
    schools = c.get("schools") or c.get("education")
    if isinstance(schools, list) and schools:
        edu = []
        for s in schools:
            if not isinstance(s, dict):
                continue
            edu.append({
                "institution": _clean(s.get("name") or s.get("institution")),
                "degree": _clean(s.get("degree")),
                "field": _clean(s.get("major") or s.get("field")),
                "end_year": s.get("grad_year") or s.get("end_year"),
            })
        if edu:
            raw["education"] = edu

    return raw


def load(path: str) -> List[SourceRecord]:
    records: List[SourceRecord] = []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return records

    # Accept either a top-level list or {"candidates": [...]}.
    if isinstance(data, dict):
        candidates = data.get("candidates") or data.get("applicants") or []
    elif isinstance(data, list):
        candidates = data
    else:
        candidates = []

    for c in candidates:
        if not isinstance(c, dict):
            continue
        raw = _map_candidate(c)
        if not raw:
            continue
        records.append(SourceRecord(
            source=SOURCE_ATS_JSON,
            raw=raw,
            methods={k: METHOD_FIELD_MAP for k in raw},
        ))
    return records
