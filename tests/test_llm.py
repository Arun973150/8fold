"""LLM extractor tests -- focus on the anti-hallucination grounding, no network."""

import os

import transformer.sources.resume_source as rs
from transformer.extract import llm_resume
from transformer.extract.llm_resume import (
    ResumeExtract, _Education, _Experience, _Links, _Location, _verify, is_enabled,
)

RESUMES = os.path.join(os.path.dirname(__file__), "..", "samples", "resumes")


def test_disabled_without_key():
    assert is_enabled() is False               # conftest strips GROQ_API_KEY
    assert llm_resume.extract("some résumé text") is None


def test_verify_drops_ungrounded_values():
    text = "Jane Doe\nSoftware Engineer at Acme\nSkills: Python, Rust\nContact: jane@x.com"
    data = ResumeExtract(
        full_name="Jane Doe",
        emails=["jane@x.com", "fake@evil.com"],           # 2nd not in text
        skills=["Python", "Rust", "Kubernetes"],          # Kubernetes not in text
        links=_Links(github="github.com/ghost"),          # not in text
        experience=[_Experience(company="Acme", title="Software Engineer"),
                    _Experience(company="Globex", title="CTO")],  # Globex invented
    )
    raw = _verify(data, text)
    assert raw["full_name"] == "Jane Doe"
    assert raw["emails"] == ["jane@x.com"]                # hallucinated email dropped
    assert set(raw["skills"]) == {"Python", "Rust"}      # Kubernetes dropped
    assert "links" not in raw                             # ungrounded github dropped
    assert [e["company"] for e in raw["experience"]] == ["Acme"]  # Globex dropped


def test_verify_empty_when_nothing_grounded():
    data = ResumeExtract(full_name="Totally Made Up", skills=["Cobol"])
    assert _verify(data, "unrelated text about cats") == {}


def test_verify_checks_every_nested_and_numeric_value():
    text = "Jane Doe\nEngineer at Acme\nBS, MIT\n5 years experience\nJan 2020"
    data = ResumeExtract(
        full_name="Jane Doe",
        experience=[_Experience(company="Acme", title="Invented CTO",
                                start="Jan 2020", end="Dec 2099")],
        education=[_Education(institution="MIT", degree="BS",
                              field="Invented Field", end_year=2099)],
        years_experience=99,
    )
    raw = _verify(data, text)
    assert raw["experience"] == [{"company": "Acme", "title": None,
                                  "start": "Jan 2020", "end": None, "summary": None}]
    assert raw["education"] == [{"institution": "MIT", "degree": "BS",
                                 "field": None, "end_year": None}]
    assert "years_experience" not in raw

    grounded = _verify(ResumeExtract(years_experience=5), text)
    assert grounded["years_experience"] == 5.0


def test_verify_location_keeps_stated_drops_inferred():
    # City stated -> kept; country NOT in text (an inference) -> dropped.
    text = "Based in Bengaluru, Karnataka"
    data = ResumeExtract(location=_Location(city="Bengaluru", region="Karnataka", country="India"))
    raw = _verify(data, text)
    assert raw["location"] == {"city": "Bengaluru", "region": "Karnataka"}
    assert "country" not in raw["location"]   # never invent country from a city


def test_load_merges_llm_record_when_enabled(monkeypatch):
    # Mock the model call; assert load emits a distinct method=llm record.
    monkeypatch.setattr(rs, "_llm_extract", lambda text: {"skills": ["PyTorch", "TEEs"]})
    recs = rs.load(os.path.join(RESUMES, "jane_doe.pdf"), use_llm=True)
    llm_recs = [r for r in recs if "llm" in r.methods.values()]
    assert len(llm_recs) == 1
    assert llm_recs[0].raw["skills"] == ["PyTorch", "TEEs"]
    # the heuristic record is still present
    assert any("regex" in r.methods.values() for r in recs)


def test_load_no_llm_record_when_disabled():
    recs = rs.load(os.path.join(RESUMES, "jane_doe.pdf"), use_llm=False)
    assert all("llm" not in r.methods.values() for r in recs)
