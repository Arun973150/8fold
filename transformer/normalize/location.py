"""Location normalization.

Goal: a ``{city, region, country}`` dict where ``country`` is an ISO-3166 alpha-2
code. Accepts either a dict (already split) or a free-text string like
"San Francisco, CA, USA". Country resolution uses pycountry plus a small alias
table for the common informal names it does not recognize on its own.
"""

from __future__ import annotations

from typing import Optional

import pycountry

# Informal names / abbreviations pycountry's fuzzy search handles poorly.
_COUNTRY_ALIASES = {
    "usa": "US", "u.s.a.": "US", "u.s.": "US", "us": "US", "america": "US",
    "united states": "US", "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "britain": "GB", "great britain": "GB",
    "england": "GB", "united kingdom": "GB",
    "uae": "AE", "south korea": "KR", "korea": "KR", "russia": "RU",
    "bharat": "IN", "india": "IN",
}


def normalize_country(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    low = s.lower()
    if low in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[low]
    # Exact alpha-2 / alpha-3 code already?
    if len(s) in (2, 3) and s.isalpha():
        try:
            rec = pycountry.countries.lookup(s)
            return rec.alpha_2
        except LookupError:
            pass
    try:
        rec = pycountry.countries.lookup(s)
        return rec.alpha_2
    except LookupError:
        return None


def normalize_location(value) -> dict:
    """Always returns a dict with the three keys; unknown parts are None."""
    out = {"city": None, "region": None, "country": None}
    if value is None:
        return out
    if isinstance(value, dict):
        city = value.get("city")
        region = value.get("region") or value.get("state")
        country = value.get("country")
        out["city"] = city.strip() if isinstance(city, str) and city.strip() else None
        out["region"] = region.strip() if isinstance(region, str) and region.strip() else None
        out["country"] = normalize_country(country) if country else None
        return out
    if not isinstance(value, str):
        return out

    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return out
    # Last part is most likely the country; try to resolve it.
    country = normalize_country(parts[-1])
    if country is not None:
        out["country"] = country
        parts = parts[:-1]
    if parts:
        out["city"] = parts[0]
    if len(parts) >= 2:
        out["region"] = parts[1]
    return out
