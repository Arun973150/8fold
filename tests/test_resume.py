"""Resume adapter tests (PDF + DOCX)."""

import os

from transformer.sources import resume_source
from transformer.pipeline import run

RESUMES = os.path.join(os.path.dirname(__file__), "..", "samples", "resumes")
SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


def test_pdf_extraction():
    recs = resume_source.load(os.path.join(RESUMES, "jane_doe.pdf"))
    assert len(recs) == 1
    raw = recs[0].raw
    assert recs[0].source == "resume"
    assert "jane.doe@example.com" in raw["emails"]
    assert raw["links"]["github"] == "octocat"          # not the literal word "github"
    assert raw["links"]["portfolio"] == "https://jane.dev"
    assert "Terraform" in [s for s in (raw.get("skills") or []) ] or "terraform" in raw["skills"]
    companies = [e["company"] for e in raw["experience"]]
    assert "Initech" in companies                        # a role only the resume has
    assert raw["education"][0]["institution"] == "MIT"


def test_docx_extraction():
    recs = resume_source.load(os.path.join(RESUMES, "carlos_reyes.docx"))
    assert len(recs) == 1
    raw = recs[0].raw
    assert "carlos.reyes@example.com" in raw["emails"]
    assert raw["links"]["portfolio"] == "https://carlosreyes.dev"
    assert "kafka" in raw["skills"]                       # raw alias; canonicalized later


def test_unreadable_file_degrades():
    # A non-existent / unreadable resume yields no records, never raises.
    assert resume_source.load(os.path.join(RESUMES, "does_not_exist.pdf")) == []


def test_resume_merges_into_candidate():
    r = run(SAMPLES, None, fetch_github=False)
    jane = next(p for p in r["profiles"] if p["candidate_id"] == "jane.doe@example.com")
    assert jane["links"]["portfolio"] == "https://jane.dev"     # contributed by the resume
    assert any(p["source"] == "resume" for p in jane["provenance"])
    assert "Initech" in [e["company"] for e in jane["experience"]]
