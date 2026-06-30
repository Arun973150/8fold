"""Email normalization: lowercase, trim, validate shape, dedupe."""

from __future__ import annotations

import re
from typing import Optional

# Deliberately permissive but not credulous: requires local@domain.tld shape.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("<>").lower()
    if not _EMAIL_RE.match(cleaned):
        return None
    return cleaned


def normalize_emails(values) -> list:
    """Normalize a list (or single value) of emails, dropping junk and dupes."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    seen: list = []
    for v in values:
        e = normalize_email(v)
        if e and e not in seen:
            seen.append(e)
    return seen
