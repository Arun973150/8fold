"""Recruiter notes adapter (unstructured / free text).

Free prose, so extraction is heuristic and openly lower-trust (method=regex). We
pull only what we can find with explicit patterns -- emails, phones, a github
handle, an optional "Name:"/first-line name, a rough years-of-experience, and any
known skill keywords. Nothing is inferred beyond what the text literally says.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

from ..model import SourceRecord, SOURCE_RECRUITER_NOTES, METHOD_REGEX
from ..normalize.skills import _ALIAS_TO_CANON  # reuse the known-skill vocabulary

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\d\-\s().]{7,}\d)")
# Prefer the github.com/<handle> URL form; the bare "github: <handle>" form uses a
# negative lookahead so it never captures the literal word "github" from a URL.
_GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9\-]+)|github\s*[:\-]\s*@?(?!github\b)([A-Za-z0-9\-]+)", re.I)
_LINKEDIN_RE = re.compile(r"linkedin\.com/in/([A-Za-z0-9\-]+)", re.I)
_NAME_RE = re.compile(r"^\s*name\s*[:\-]\s*(.+)$", re.I | re.M)
_YEARS_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\+?\s*(?:years|yrs)\b", re.I)


def _find_skills(text: str) -> List[str]:
    low = text.lower()
    found = []
    for alias in _ALIAS_TO_CANON:
        # word-boundary match so "go" doesn't match "google"
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", low):
            found.append(alias)
    return found


def _guess_name(text: str) -> Optional[str]:
    m = _NAME_RE.search(text)
    if m:
        return m.group(1).strip()
    # Fallback: a short, capitalized first non-empty line that looks like a name.
    for line in text.splitlines():
        line = line.strip()
        if 2 <= len(line.split()) <= 4 and line.replace(" ", "").isalpha() and line[0].isupper():
            return line
        if line:
            break
    return None


def parse_text(text: str) -> dict:
    raw = {}

    emails = _EMAIL_RE.findall(text)
    if emails:
        raw["emails"] = emails

    phones = [p.strip() for p in _PHONE_RE.findall(text)]
    if phones:
        raw["phones"] = phones

    links = {}
    gh_match = _GITHUB_RE.search(text)
    if gh_match:
        handle = gh_match.group(1) or gh_match.group(2)
        if handle:
            links["github"] = handle
    li_match = _LINKEDIN_RE.search(text)
    if li_match:
        links["linkedin"] = "https://www.linkedin.com/in/" + li_match.group(1)
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

    return raw


def load(path: str) -> List[SourceRecord]:
    """Load a single .txt file or a directory of .txt files."""
    paths: List[str] = []
    if os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            if name.lower().endswith(".txt"):
                paths.append(os.path.join(path, name))
    else:
        paths.append(path)

    records: List[SourceRecord] = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        raw = parse_text(text)
        if not raw:
            continue
        records.append(SourceRecord(
            source=SOURCE_RECRUITER_NOTES,
            raw=raw,
            methods={k: METHOD_REGEX for k in raw},
        ))
    return records
