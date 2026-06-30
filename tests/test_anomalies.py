"""Anomaly detection heuristics."""

from transformer.model import Profile
from transformer.trust.anomalies import detect


def _p(**kw):
    return Profile(candidate_id="c", **kw)


def test_implausible_years():
    a = detect(_p(years_experience=120))
    assert any(x["type"] == "implausible_years_experience" for x in a)
    assert detect(_p(years_experience=8)) == []


def test_future_dates():
    a = detect(_p(education=[{"institution": "X", "degree": "BS", "field": "CS", "end_year": 2031}]),
               reference_year=2026)
    assert any(x["type"] == "future_date" for x in a)


def test_inverted_date_range():
    a = detect(_p(experience=[{"company": "X", "title": "Eng", "start": "2022-05", "end": "2020-01"}]))
    assert any(x["type"] == "inverted_date_range" for x in a)


def test_email_name_mismatch():
    a = detect(_p(full_name="Jane Doe", emails=["zzz999@example.com"]))
    assert any(x["type"] == "email_name_mismatch" for x in a)
    # a matching email is not flagged
    assert detect(_p(full_name="Jane Doe", emails=["jane.doe@example.com"])) == []


def test_clean_profile_has_no_anomalies():
    p = _p(full_name="Jane Doe", emails=["jane.doe@example.com"], years_experience=8,
           experience=[{"company": "Acme", "title": "Eng", "start": "2019-01", "end": "2021-06"}],
           education=[{"institution": "MIT", "degree": "BS", "field": "CS", "end_year": 2017}])
    assert detect(p) == []
