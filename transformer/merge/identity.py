"""Incremental identity resolution.

The batch path clusters within one run. For a stateful, growing store we instead
resolve one incoming record against what already exists:

1. **Blocking** -- extract strong keys (email / phone / github) and a weak key
   (normalized name). Only candidates that share a key are even considered, so we
   never compare against the whole database (no O(n^2)).
2. **Scoring** -- a shared strong key is a near-certain match; otherwise we fall
   back to fuzzy name similarity above a conservative threshold.

This is the same conservative philosophy as the batch clusterer, made incremental.
"""

from __future__ import annotations

from typing import List, Tuple

from rapidfuzz import fuzz

from ..model import SourceRecord
from ..normalize.emails import normalize_emails
from ..normalize.phones import normalize_phones

STRONG = ("email", "phone", "github")
NAME_MATCH_THRESHOLD = 92  # 0-100; only link on name alone when very similar


def _github_handle(record: SourceRecord):
    links = record.raw.get("links")
    if isinstance(links, dict) and links.get("github"):
        raw = str(links["github"]).strip().rstrip("/")
        if "github.com/" in raw:
            raw = raw.split("github.com/")[-1].split("/")[0]
        return raw.lstrip("@").lower() or None
    return None


def blocking_keys(record: SourceRecord) -> List[Tuple[str, str]]:
    """Return (key_type, key_value) pairs for blocking lookups."""
    keys: List[Tuple[str, str]] = []
    for e in normalize_emails(record.raw.get("emails")):
        keys.append(("email", e))
    for p in normalize_phones(record.raw.get("phones")):
        keys.append(("phone", p))
    gh = _github_handle(record)
    if gh:
        keys.append(("github", gh))
    name = record.raw.get("full_name")
    if isinstance(name, str) and name.strip():
        keys.append(("name", name.strip().lower()))
    return keys


def name_of(keys: List[Tuple[str, str]]):
    for t, v in keys:
        if t == "name":
            return v
    return None


def score(existing_keys: List[Tuple[str, str]], incoming_keys: List[Tuple[str, str]]) -> float:
    """Match score in [0,1] between an existing candidate and an incoming record."""
    ex_strong = {(t, v) for t, v in existing_keys if t in STRONG}
    in_strong = {(t, v) for t, v in incoming_keys if t in STRONG}
    if ex_strong & in_strong:
        return 1.0  # any shared strong key -> same person
    # A common/similar name must not override conflicting or one-sided strong
    # identity evidence. Name fallback is only for two records with no strong keys.
    if ex_strong or in_strong:
        return 0.0
    en, inn = name_of(existing_keys), name_of(incoming_keys)
    if en and inn:
        ratio = fuzz.token_sort_ratio(en, inn)
        if ratio >= NAME_MATCH_THRESHOLD:
            return round(ratio / 100.0, 4)
    return 0.0


LINK_THRESHOLD = 0.9  # below this, treat as a new candidate
