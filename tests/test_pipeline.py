"""End-to-end tests: deterministic default run (gold compare), mocked-GitHub
enrichment, robustness, and strict-config error isolation."""

import json
import os

import jsonschema

from transformer.pipeline import run
from transformer.model import DEFAULT_SCHEMA
from transformer.sources import github_source

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")
GOLD = os.path.join(os.path.dirname(__file__), "gold", "default.json")


def test_default_run_matches_gold_and_validates():
    result = run(SAMPLES, None, fetch_github=False)
    # every profile is schema-valid
    for view in result["profiles"]:
        jsonschema.validate(view, DEFAULT_SCHEMA)
    # deterministic: byte-for-byte stable against the committed gold
    with open(GOLD, encoding="utf-8") as fh:
        gold = json.load(fh)
    assert result["profiles"] == gold
    assert result["errors"] == []


def test_robust_to_garbage_source():
    # samples/broken.json is invalid JSON; the run must still succeed.
    result = run(SAMPLES, None, fetch_github=False)
    assert len(result["profiles"]) == 3


def test_github_enrichment_is_mockable_and_deterministic(monkeypatch):
    def fake_get(url, params=None):
        if url.endswith("/users/octocat"):
            return {"name": "The Octocat", "bio": "Mascot", "blog": "https://github.blog",
                    "html_url": "https://github.com/octocat", "location": "San Francisco"}
        if url.endswith("/users/octocat/repos"):
            return [{"language": "Ruby"}, {"language": "Python"}, {"language": None}]
        return None  # any other handle (e.g. the fake one) -> degrade

    monkeypatch.setattr(github_source, "_http_get_json", fake_get)
    result = run(SAMPLES, None, fetch_github=True)
    jane = next(p for p in result["profiles"] if p["candidate_id"] == "jane.doe@example.com")
    skill_names = {s["name"] for s in jane["skills"]}
    assert "Ruby" in skill_names                      # enriched from GitHub repos
    assert any(p["source"] == "github" for p in jane["provenance"])
    assert result["errors"] == []                      # fake handle degraded, no crash


def test_strict_config_isolates_missing_required():
    strict = {
        "fields": [
            {"path": "full_name", "type": "string", "required": True},
            {"path": "primary_email", "from": "emails[0]", "type": "string", "required": True},
        ],
        "on_missing": "error",
    }
    result = run(SAMPLES, strict, fetch_github=False)
    assert len(result["profiles"]) == 2               # Jane + Carlos
    assert len(result["errors"]) == 1                 # Sam Lee has no email
    assert result["errors"][0]["candidate_id"] == "sam-lee"
