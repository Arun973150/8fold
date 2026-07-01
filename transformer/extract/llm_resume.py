"""Grounded, extractive résumé parsing via LangChain + Groq.

Anti-hallucination design (three layers):

1. **Prompt** -- the model is told to copy verbatim, output null when a field is
   absent, and never infer or invent.
2. **Structured output** -- the response is forced into a typed Pydantic schema
   (temperature 0), so we never parse free-form prose.
3. **Grounding verification** -- every returned string is checked against the
   source text; anything that doesn't actually appear there is discarded. This is
   the hard guarantee: the extractor can only surface things the résumé really says.

Configuration lives in ``.env`` (GROQ_API_KEY, optional GROQ_MODEL). If the key is
missing or any error occurs, ``extract`` returns None and the caller falls back to
the deterministic heuristic parser.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()  # pull GROQ_API_KEY / GROQ_MODEL from .env if present

DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

_SYSTEM = (
    "You are a strict, extractive résumé parser. Extract ONLY information that is "
    "literally present in the résumé text. Copy values verbatim. If a field is not "
    "present, leave it null or an empty list. NEVER guess, infer, normalize, expand "
    "abbreviations, or invent anything. Do not add skills, employers, schools, or "
    "dates that are not written in the text. It is far better to leave a field empty "
    "than to include anything uncertain."
)


# --- typed output schema (forces structured, not free-form, responses) -------- #
class _Experience(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = Field(None, description="verbatim as written, e.g. 'Dec 2025'")
    end: Optional[str] = Field(None, description="verbatim, or 'present'")
    summary: Optional[str] = None


class _Education(BaseModel):
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None


class _Links(BaseModel):
    github: Optional[str] = None
    linkedin: Optional[str] = None
    portfolio: Optional[str] = None


class _Location(BaseModel):
    city: Optional[str] = Field(None, description="verbatim, only if stated")
    region: Optional[str] = None
    country: Optional[str] = Field(None, description="verbatim country as written; do NOT infer from a city")


class ResumeExtract(BaseModel):
    full_name: Optional[str] = None
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    links: Optional[_Links] = None
    location: Optional[_Location] = None
    skills: List[str] = Field(default_factory=list)
    experience: List[_Experience] = Field(default_factory=list)
    education: List[_Education] = Field(default_factory=list)
    years_experience: Optional[float] = None


def is_enabled() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


# --- grounding: keep only what actually appears in the source text ------------ #
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _grounded(value, haystack: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return _norm(value) in haystack


def _grounded_number(value, text: str) -> bool:
    """Require a numeric model value to occur as a complete source token."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    forms = {str(value)}
    if isinstance(value, float) and value.is_integer():
        forms.add(str(int(value)))
    return any(re.search(rf"(?<![\d.]){re.escape(form)}(?![\d.])", text) for form in forms)


def _verify(data: ResumeExtract, text: str) -> dict:
    """Drop any value that is not grounded in the résumé text."""
    hay = _norm(text)
    raw: dict = {}

    if _grounded(data.full_name, hay):
        raw["full_name"] = data.full_name.strip()

    emails = [e for e in data.emails if _grounded(e, hay)]
    if emails:
        raw["emails"] = emails
    # A phone is grounded if its digits appear in the résumé's digits (ignores
    # punctuation/spacing differences).
    text_digits = re.sub(r"\D", "", text)
    phones = [p for p in data.phones
              if isinstance(p, str) and (d := re.sub(r"\D", "", p)) and d in text_digits]
    if phones:
        raw["phones"] = phones

    if data.links:
        links = {}
        for k in ("github", "linkedin", "portfolio"):
            v = getattr(data.links, k)
            if _grounded(v, hay):
                links[k] = v.strip()
        if links:
            raw["links"] = links

    if data.location:
        loc = {}
        for k in ("city", "region", "country"):
            v = getattr(data.location, k)
            if _grounded(v, hay):
                loc[k] = v.strip()
        if loc:
            # raw strings only; the deterministic normalizer maps country -> ISO.
            raw["location"] = loc

    skills = [s.strip() for s in data.skills if _grounded(s, hay)]
    if skills:
        raw["skills"] = skills

    exp = []
    for e in data.experience:
        company = e.company.strip() if _grounded(e.company, hay) else None
        title = e.title.strip() if _grounded(e.title, hay) else None
        # One real company must not legitimize invented dates or a fake title.
        if company or title:
            exp.append({
                "company": company,
                "title": title,
                "start": e.start.strip() if _grounded(e.start, hay) else None,
                "end": e.end.strip() if _grounded(e.end, hay) else None,
                "summary": e.summary.strip() if _grounded(e.summary, hay) else None,
            })
    if exp:
        raw["experience"] = exp

    edu = []
    for e in data.education:
        institution = e.institution.strip() if _grounded(e.institution, hay) else None
        degree = e.degree.strip() if _grounded(e.degree, hay) else None
        if institution or degree:
            edu.append({
                "institution": institution,
                "degree": degree,
                "field": e.field.strip() if _grounded(e.field, hay) else None,
                "end_year": e.end_year if _grounded_number(e.end_year, text) else None,
            })
    if edu:
        raw["education"] = edu

    if _grounded_number(data.years_experience, text):
        raw["years_experience"] = float(data.years_experience)

    return raw


def extract(text: str) -> Optional[dict]:
    """Return a verified canonical-keyed raw dict, or None if unavailable/failed."""
    if not text or not text.strip() or not is_enabled():
        return None
    try:
        from langchain_groq import ChatGroq

        llm = ChatGroq(model=DEFAULT_MODEL, temperature=0).with_structured_output(ResumeExtract)
        result = llm.invoke([("system", _SYSTEM), ("human", text)])
        if not isinstance(result, ResumeExtract):
            return None
        verified = _verify(result, text)
        return verified or None
    except Exception:
        # Any failure (no network, bad key, rate limit, schema error) -> fall back.
        return None
