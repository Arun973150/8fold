"""Date normalization to "YYYY-MM" (or "YYYY" when only the year is known).

Supported inputs include: 2021-03, 2021/03, 03/2021, "March 2021", "Mar 2021",
2021, and the open-ended markers present/current/now (which map to ``None`` so an
ongoing role reads as end=null). Year-only inputs stay year-only -- we refuse to
invent a month. Unparseable input returns ``None``.
"""

from __future__ import annotations

import re
from typing import Optional

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_PRESENT = {"present", "current", "now", "ongoing", "till date", "to date"}


def _fmt(year: int, month: Optional[int]) -> Optional[str]:
    if not (1900 <= year <= 2100):
        return None
    if month is None:
        return f"{year:04d}"
    if not (1 <= month <= 12):
        return f"{year:04d}"
    return f"{year:04d}-{month:02d}"


def normalize_date(value) -> Optional[str]:
    """Return a YYYY-MM / YYYY string, or None (None also means 'present')."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _fmt(int(value), None)
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if not s or s in _PRESENT:
        return None

    # ISO-ish: 2021-03, 2021/03, 2021.03, or 2021-03-15 (day dropped)
    m = re.match(r"^(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?$", s)
    if m:
        return _fmt(int(m.group(1)), int(m.group(2)))

    # US-ish: 03/2021 or 3-2021
    m = re.match(r"^(\d{1,2})[-/.](\d{4})$", s)
    if m:
        return _fmt(int(m.group(2)), int(m.group(1)))

    # Month name + year: "march 2021", "mar 2021", "march, 2021"
    m = re.match(r"^([a-z]+)\.?,?\s+(\d{4})$", s)
    if m and m.group(1) in _MONTHS:
        return _fmt(int(m.group(2)), _MONTHS[m.group(1)])

    # Year + month name: "2021 march"
    m = re.match(r"^(\d{4})\s+([a-z]+)\.?$", s)
    if m and m.group(2) in _MONTHS:
        return _fmt(int(m.group(1)), _MONTHS[m.group(2)])

    # Bare year
    m = re.match(r"^(\d{4})$", s)
    if m:
        return _fmt(int(m.group(1)), None)

    return None


def normalize_year(value) -> Optional[int]:
    """Extract a 4-digit graduation/end year as an int, or None."""
    d = normalize_date(value)
    if d is None:
        return None
    return int(d[:4])
