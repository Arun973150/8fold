"""Recruiter CSV export adapter (structured source).

Expected columns: name, email, phone, current_company, title. Extra/missing
columns are tolerated. Each row becomes one SourceRecord. The current company +
title become a single open-ended experience entry (end unknown -> present).
"""

from __future__ import annotations

import csv
from typing import List

from ..model import SourceRecord, SOURCE_RECRUITER_CSV, METHOD_FIELD_MAP


def _clean(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def load(path: str) -> List[SourceRecord]:
    records: List[SourceRecord] = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                row = { (k or "").strip().lower(): v for k, v in row.items() }
                name = _clean(row.get("name"))
                email = _clean(row.get("email"))
                phone = _clean(row.get("phone"))
                company = _clean(row.get("current_company"))
                title = _clean(row.get("title"))

                raw = {}
                if name:
                    raw["full_name"] = name
                if email:
                    raw["emails"] = [email]
                if phone:
                    raw["phones"] = [phone]
                if company or title:
                    raw["experience"] = [{
                        "company": company,
                        "title": title,
                        "start": None,
                        "end": None,   # current role; resolver treats None end as present
                        "summary": None,
                    }]
                if not raw:
                    continue
                records.append(SourceRecord(
                    source=SOURCE_RECRUITER_CSV,
                    raw=raw,
                    methods={k: METHOD_FIELD_MAP for k in raw},
                ))
    except (OSError, csv.Error):
        # Garbage / missing file must not crash the run.
        return records
    return records
