"""Trust layer tests: explain trace, quality/conflict report, review gating."""

import os

from transformer.pipeline import run
from transformer.merge.resolver import resolve
from transformer.model import (
    SourceRecord, SOURCE_ATS_JSON, SOURCE_RECRUITER_CSV, SOURCE_RECRUITER_NOTES,
)
from transformer.trust.build import quality_report, completeness, build_trust

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


def test_explain_trace_records_losers_on_conflict():
    ats = SourceRecord(SOURCE_ATS_JSON, {"full_name": "Jane A. Doe", "emails": ["j@x.com"]})
    csv = SourceRecord(SOURCE_RECRUITER_CSV, {"full_name": "Jane Doe", "emails": ["j@x.com"]})
    p = resolve([ats, csv], "j@x.com")
    dec = p.trace["full_name"]
    assert dec["chosen"] == "Jane A. Doe"
    assert dec["conflict"] is True
    # both the winner and the loser are recorded
    values = {(c["value"], c["won"]) for c in dec["considered"]}
    assert ("Jane A. Doe", True) in values
    assert ("Jane Doe", False) in values


def test_quality_report_flags_sparse_no_email():
    notes = SourceRecord(SOURCE_RECRUITER_NOTES, {"full_name": "Sam Lee", "skills": ["python"]})
    p = resolve([notes], "sam-lee")
    rep = quality_report(p, threshold=0.6)
    assert rep["needs_review"] is True
    assert "no_email" in rep["flags"]
    assert any("no email" in r for r in rep["review_reasons"])
    assert rep["completeness"] < 0.5


def test_completeness_full_vs_sparse():
    full = SourceRecord(SOURCE_ATS_JSON, {
        "full_name": "A", "emails": ["a@b.com"], "phones": ["+14155550132"],
        "location": {"country": "US"}, "headline": "Eng", "years_experience": 5,
        "skills": ["python"],
        "experience": [{"company": "X", "title": "Eng"}],
        "education": [{"institution": "MIT", "degree": "BS"}],
    })
    sparse = SourceRecord(SOURCE_RECRUITER_NOTES, {"full_name": "B"})
    assert completeness(resolve([full], "a@b.com")) == 1.0
    assert completeness(resolve([sparse], "b")) < 0.3


def test_build_trust_batch_and_review_queue():
    result = run(SAMPLES, None, fetch_github=False, trust=True, review_threshold=0.6)
    trust = result["trust"]
    assert trust["batch"]["total"] == 3
    # Sam (sparse/no-email) + Carlos (anomaly: future grad year) both flagged.
    assert trust["batch"]["needs_review"] == 2
    assert trust["batch"]["review_queue"] == ["carlos.reyes@example.com", "sam-lee"]
    # the name conflict is rolled up at the batch level
    assert trust["batch"]["conflict_field_counts"].get("full_name") == 1
    # every candidate carries an explain trace
    assert all("explain" in c for c in trust["candidates"])


def test_threshold_raises_review_count():
    lenient = run(SAMPLES, None, fetch_github=False, trust=True, review_threshold=0.0)
    strict = run(SAMPLES, None, fetch_github=False, trust=True, review_threshold=0.95)
    assert strict["trust"]["batch"]["needs_review"] >= lenient["trust"]["batch"]["needs_review"]
