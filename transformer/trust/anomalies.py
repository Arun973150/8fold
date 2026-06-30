"""Heuristic anomaly detection -- a data-quality signal beyond conflicts.

Conflicts catch *sources disagreeing*. Anomalies catch values that are internally
implausible even when every source agrees -- the kind of well-formed-but-wrong data
that "honestly-empty beats wrong-but-confident" is meant to guard against.

All checks are deterministic. "Future" is judged against a fixed ``REFERENCE_YEAR``
(not the wall clock) so output stays reproducible; bump it as the reference moves.
"""

from __future__ import annotations

import re
from typing import List

from ..model import Profile

REFERENCE_YEAR = 2026
MAX_PLAUSIBLE_YEARS = 60   # years of professional experience

_TOKEN_RE = re.compile(r"[a-z]{3,}")


def _year(date_str) -> int:
    return int(str(date_str)[:4]) if date_str else None


def _name_tokens(name: str) -> List[str]:
    return _TOKEN_RE.findall(name.lower()) if isinstance(name, str) else []


def detect(profile: Profile, reference_year: int = REFERENCE_YEAR) -> List[dict]:
    out: List[dict] = []

    ye = profile.years_experience
    if ye is not None and (ye < 0 or ye > MAX_PLAUSIBLE_YEARS):
        out.append({"type": "implausible_years_experience", "field": "years_experience",
                    "detail": f"{ye} years"})

    for e in profile.experience:
        for key in ("start", "end"):
            y = _year(e.get(key))
            if y and y > reference_year:
                out.append({"type": "future_date", "field": "experience",
                            "detail": f"{key}={e.get(key)}"})
        s, en = e.get("start"), e.get("end")
        # Only compare when both are full YYYY-MM to avoid year-vs-month ambiguity.
        if s and en and len(s) == 7 and len(en) == 7 and s > en:
            out.append({"type": "inverted_date_range", "field": "experience",
                        "detail": f"{s} > {en}"})

    for ed in profile.education:
        y = ed.get("end_year")
        if isinstance(y, int) and y > reference_year:
            out.append({"type": "future_date", "field": "education",
                        "detail": f"end_year={y}"})

    # Email whose local-part shares no token with the candidate's name.
    tokens = _name_tokens(profile.full_name)
    if tokens and profile.emails:
        if not any(any(t in em.split("@")[0].lower() for t in tokens) for em in profile.emails):
            out.append({"type": "email_name_mismatch", "field": "emails",
                        "detail": profile.emails[0]})

    return out
