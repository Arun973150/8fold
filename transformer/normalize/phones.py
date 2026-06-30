"""Phone normalization to E.164 using Google's libphonenumber (phonenumbers).

A number with an explicit ``+`` country code is parsed directly. A bare national
number is parsed against a default region (configurable; US by default). Anything
that does not parse to a *valid* number returns ``None`` -- we never emit a
half-formed or guessed phone.
"""

from __future__ import annotations

from typing import Optional

import phonenumbers

DEFAULT_REGION = "US"


def normalize_phone(value, default_region: str = DEFAULT_REGION) -> Optional[str]:
    if not isinstance(value, (str, int)):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    region = None if raw.startswith("+") else default_region
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_phones(values, default_region: str = DEFAULT_REGION) -> list:
    if values is None:
        return []
    if isinstance(values, (str, int)):
        values = [values]
    seen: list = []
    for v in values:
        p = normalize_phone(v, default_region)
        if p and p not in seen:
            seen.append(p)
    return seen
