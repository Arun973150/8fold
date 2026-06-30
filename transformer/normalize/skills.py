"""Skill canonicalization.

Two-step, fully deterministic:

1. An explicit alias map collapses the obvious surface variants
   ("reactjs"/"react.js"/"react" -> "React").
2. For anything not in the map, a fuzzy match (rapidfuzz) against the set of
   known canonical names catches near-misses ("javascrpt" -> "JavaScript") above
   a fixed score threshold. Below threshold we keep the original (title-cased)
   rather than guess wrong -- an unknown skill is reported, never invented away.
"""

from __future__ import annotations

from typing import Optional

from rapidfuzz import process, fuzz

# Canonical name -> the surface forms that should collapse onto it.
_CANON = {
    "JavaScript": ["javascript", "js", "java script", "ecmascript"],
    "TypeScript": ["typescript", "ts"],
    "Python": ["python", "py", "python3"],
    "Java": ["java"],
    "Go": ["go", "golang"],
    "C++": ["c++", "cpp", "cplusplus"],
    "C#": ["c#", "csharp", "c sharp"],
    "React": ["react", "reactjs", "react.js"],
    "Node.js": ["node", "nodejs", "node.js"],
    "Django": ["django"],
    "Flask": ["flask"],
    "SQL": ["sql"],
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "AWS": ["aws", "amazon web services"],
    "GCP": ["gcp", "google cloud", "google cloud platform"],
    "Machine Learning": ["machine learning", "ml"],
    "REST": ["rest", "rest api", "restful"],
    "GraphQL": ["graphql"],
    "Terraform": ["terraform"],
    "Kafka": ["kafka", "apache kafka"],
    "Redis": ["redis"],
    "Spark": ["spark", "apache spark"],
}

# Build reverse lookup: surface form -> canonical name.
_ALIAS_TO_CANON = {}
for canon, aliases in _CANON.items():
    _ALIAS_TO_CANON[canon.lower()] = canon
    for a in aliases:
        _ALIAS_TO_CANON[a] = canon

_CANON_NAMES = list(_CANON.keys())
_FUZZY_THRESHOLD = 88  # 0-100; conservative so we do not mis-merge distinct skills


def normalize_skill(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    key = s.lower()
    if key in _ALIAS_TO_CANON:
        return _ALIAS_TO_CANON[key]
    # Fuzzy fallback against canonical names only.
    match = process.extractOne(s, _CANON_NAMES, scorer=fuzz.WRatio)
    if match and match[1] >= _FUZZY_THRESHOLD:
        return match[0]
    # Unknown but real: keep it, lightly cleaned. Never drop, never invent.
    return s


def normalize_skills(values) -> list:
    """Normalize and dedupe a list of skill names (order preserved)."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    seen: list = []
    for v in values:
        s = normalize_skill(v)
        if s and s not in seen:
            seen.append(s)
    return seen
