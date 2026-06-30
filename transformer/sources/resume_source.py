"""Resume adapter (unstructured -> PDF / DOCX prose).

Two stages: (1) pull plain text out of the file -- pdfplumber for PDF, python-docx
for DOCX; (2) heuristically extract fields from that text. Contact details, links
and skills reuse the recruiter-notes patterns; experience and education are parsed
from their labelled sections using common, documented layouts.

Resume data is openly lower-trust (method=regex), so it never out-ranks the ATS.
Anything that doesn't match a known pattern is skipped, not guessed -- a garbled or
image-only PDF simply yields fewer fields, never a crash.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

from ..model import SourceRecord, SOURCE_RESUME, METHOD_REGEX
from .notes_source import (
    _EMAIL_RE, _PHONE_RE, _GITHUB_RE, _LINKEDIN_RE, _YEARS_RE,
    _find_skills, _guess_name,
)

_PORTFOLIO_RE = re.compile(r"(?:portfolio|website)\s*[:\-]?\s*(https?://\S+)", re.I)
# "Staff Engineer at Acme Corp (2021-03 to present)"
_EXP_RE = re.compile(r"^(?P<title>.+?)\s+at\s+(?P<company>.+?)\s*\((?P<span>[^)]+)\)\s*$", re.I)
# "B.S. in Computer Science, MIT, 2017"
_EDU_RE = re.compile(r"^(?P<deg>.+?),\s*(?P<inst>.+?),\s*(?P<year>\d{4})\s*$")


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #
def _clean(text: str) -> str:
    # Some PDF fonts decode dashes/bullets to the U+FFFD replacement char; map it
    # back to a hyphen so date ranges and separators stay parseable.
    return text.replace("�", "-")


def extract_text(path: str) -> str:
    low = path.lower()
    try:
        if low.endswith(".pdf"):
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return _clean("\n".join((page.extract_text() or "") for page in pdf.pages))
        if low.endswith(".docx"):
            import docx
            doc = docx.Document(path)
            return _clean("\n".join(p.text for p in doc.paragraphs))
    except Exception:
        # Corrupt / image-only / unreadable file -> no text, no crash.
        return ""
    return ""


# --------------------------------------------------------------------------- #
# Section-aware field extraction
# --------------------------------------------------------------------------- #
def _section(lines: List[str], heading: str) -> List[str]:
    """Return the lines under a heading until the next heading / blank gap."""
    out, capturing = [], False
    for line in lines:
        stripped = line.strip()
        if not capturing:
            if stripped.lower() == heading.lower():
                capturing = True
            continue
        # Stop at a blank line or the next single-word/Title heading.
        if not stripped:
            break
        if stripped.istitle() and len(stripped.split()) == 1 and stripped.lower() != heading.lower():
            break
        out.append(stripped)
    return out


def _parse_span(span: str):
    parts = re.split(r"\s+(?:to|until|–|—)\s+", span, maxsplit=1)
    start = parts[0].strip() if parts else None
    end = parts[1].strip() if len(parts) > 1 else None
    return start, end


def parse_text(text: str) -> dict:
    raw = {}
    if not text.strip():
        return raw
    lines = text.splitlines()

    emails = _EMAIL_RE.findall(text)
    if emails:
        raw["emails"] = emails
    phones = [p.strip() for p in _PHONE_RE.findall(text)]
    if phones:
        raw["phones"] = phones

    links = {}
    gh = _GITHUB_RE.search(text)
    if gh and (gh.group(1) or gh.group(2)):
        links["github"] = gh.group(1) or gh.group(2)
    li = _LINKEDIN_RE.search(text)
    if li:
        links["linkedin"] = "https://www.linkedin.com/in/" + li.group(1)
    pf = _PORTFOLIO_RE.search(text)
    if pf:
        links["portfolio"] = pf.group(1)
    if links:
        raw["links"] = links

    name = _guess_name(text)
    if name:
        raw["full_name"] = name

    ym = _YEARS_RE.search(text)
    if ym:
        try:
            raw["years_experience"] = float(ym.group(1))
        except ValueError:
            pass

    skills = _find_skills(text)
    if skills:
        raw["skills"] = skills

    experience = []
    for line in _section(lines, "Experience") or _section(lines, "Work Experience"):
        m = _EXP_RE.match(line)
        if m:
            start, end = _parse_span(m.group("span"))
            experience.append({
                "company": m.group("company").strip(), "title": m.group("title").strip(),
                "start": start, "end": end, "summary": None,
            })
    if experience:
        raw["experience"] = experience

    education = []
    for line in _section(lines, "Education"):
        m = _EDU_RE.match(line)
        if m:
            deg = m.group("deg").strip()
            degree, field = (deg.split(" in ", 1) + [None])[:2] if " in " in deg else (deg, None)
            education.append({
                "institution": m.group("inst").strip(), "degree": degree.strip(),
                "field": field.strip() if field else None, "end_year": int(m.group("year")),
            })
    if education:
        raw["education"] = education

    return raw


def load(path: str) -> List[SourceRecord]:
    """Load a single resume file or a directory of resumes (.pdf / .docx)."""
    paths: List[str] = []
    if os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            if name.lower().endswith((".pdf", ".docx")):
                paths.append(os.path.join(path, name))
    else:
        paths.append(path)

    records: List[SourceRecord] = []
    for p in paths:
        raw = parse_text(extract_text(p))
        if not raw:
            continue
        records.append(SourceRecord(
            source=SOURCE_RESUME,
            raw=raw,
            methods={k: METHOD_REGEX for k in raw},
        ))
    return records
