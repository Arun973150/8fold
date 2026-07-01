"""Clustering and conflict-resolution tests."""

from transformer.model import (
    SourceRecord, SOURCE_ATS_JSON, SOURCE_RECRUITER_CSV, SOURCE_RECRUITER_NOTES,
    SOURCE_GITHUB, SOURCE_RESUME, METHOD_FIELD_MAP, METHOD_REGEX, METHOD_API,
)
from transformer.merge.resolver import cluster, resolve


def test_github_name_downweighted_vs_resume():
    # A GitHub display name is a nickname; per-field trust makes the résumé win.
    gh = SourceRecord(SOURCE_GITHUB, {"full_name": "void", "emails": ["a@b.com"]}, {"full_name": METHOD_API})
    rv = SourceRecord(SOURCE_RESUME, {"full_name": "Arun N", "emails": ["a@b.com"]}, {"full_name": METHOD_REGEX})
    assert resolve([gh, rv], "a@b.com").full_name == "Arun N"
    # ...but GitHub still supplies a name when it is the only source.
    assert resolve([gh], "a@b.com").full_name == "void"


def test_cluster_by_shared_email():
    a = SourceRecord(SOURCE_RECRUITER_CSV, {"full_name": "Jane Doe", "emails": ["jane@x.com"]})
    b = SourceRecord(SOURCE_ATS_JSON, {"full_name": "Jane A. Doe", "emails": ["jane@x.com"]})
    c = SourceRecord(SOURCE_RECRUITER_CSV, {"full_name": "Bob", "emails": ["bob@x.com"]})
    groups = cluster([a, b, c])
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2]  # Jane records merge, Bob alone


def test_scalar_winner_by_reliability_weight():
    # ATS (weight .9) should beat notes (weight .5) for full_name.
    ats = SourceRecord(SOURCE_ATS_JSON, {"full_name": "Jane A. Doe", "emails": ["j@x.com"]},
                       {"full_name": METHOD_FIELD_MAP})
    notes = SourceRecord(SOURCE_RECRUITER_NOTES, {"full_name": "jane", "emails": ["j@x.com"]},
                         {"full_name": METHOD_REGEX})
    profile = resolve([ats, notes], "j@x.com")
    assert profile.full_name == "Jane A. Doe"
    # both sources recorded in provenance even though notes lost
    name_sources = {p["source"] for p in profile.provenance if p["field"] == "full_name"}
    assert name_sources == {SOURCE_ATS_JSON, SOURCE_RECRUITER_NOTES}


def test_skill_corroboration_boosts_confidence():
    ats = SourceRecord(SOURCE_ATS_JSON, {"emails": ["j@x.com"], "skills": ["python"]})
    notes = SourceRecord(SOURCE_RECRUITER_NOTES, {"emails": ["j@x.com"], "skills": ["Python"]})
    one = resolve([ats], "j@x.com")
    two = resolve([ats, notes], "j@x.com")
    c_one = one.skills[0]["confidence"]
    c_two = two.skills[0]["confidence"]
    assert two.skills[0]["sources"] == [SOURCE_ATS_JSON, SOURCE_RECRUITER_NOTES]
    assert c_two > c_one  # corroboration raises confidence
