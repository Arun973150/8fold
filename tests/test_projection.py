"""Projection + path-resolver + validation tests, including on_missing policies."""

import pytest
import jsonschema

from transformer.model import Profile
from transformer.projection.paths import resolve_path
from transformer.projection.project import project, ProjectionError
from transformer.projection.validate import validate


def _profile():
    p = Profile(candidate_id="c1", full_name="Jane Doe")
    p.emails = ["jane@example.com"]
    p.phones = ["+14155550132"]
    p.location = {"city": "SF", "region": "CA", "country": "US"}
    p.skills = [{"name": "Python", "confidence": 0.9, "sources": ["ats_json"]}]
    p.overall_confidence = 0.9
    return p


def test_path_resolver():
    root = _profile().to_dict()
    assert resolve_path(root, "full_name") == (True, "Jane Doe")
    assert resolve_path(root, "emails[0]") == (True, "jane@example.com")
    assert resolve_path(root, "location.country") == (True, "US")
    assert resolve_path(root, "skills[].name") == (True, ["Python"])
    assert resolve_path(root, "emails[5]")[0] is False
    assert resolve_path(root, "nope")[0] is False


def test_projection_remap_and_normalize():
    cfg = {
        "fields": [
            {"path": "primary_email", "from": "emails[0]", "type": "string", "required": True},
            {"path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical"},
        ],
        "include_confidence": True,
        "on_missing": "null",
    }
    view = project(_profile(), cfg)
    assert view["primary_email"] == "jane@example.com"
    assert view["skills"] == ["Python"]
    assert view["overall_confidence"] == 0.9
    validate(view, cfg)  # should not raise


def test_on_missing_null_and_omit():
    base = {"fields": [{"path": "headline", "from": "headline", "type": "string"}]}
    p = _profile()  # headline is None

    v_null = project(p, {**base, "on_missing": "null"})
    assert v_null["headline"] is None

    v_omit = project(p, {**base, "on_missing": "omit"})
    assert "headline" not in v_omit


def test_on_missing_error_raises():
    cfg = {
        "fields": [{"path": "headline", "from": "headline", "type": "string", "required": True}],
        "on_missing": "error",
    }
    with pytest.raises(ProjectionError):
        project(_profile(), cfg)


def test_validation_rejects_wrong_type():
    # required string field that is actually null must fail validation
    cfg = {"fields": [{"path": "primary_email", "from": "headline", "type": "string", "required": True}],
           "on_missing": "null"}
    view = project(_profile(), cfg)  # headline None -> primary_email null
    with pytest.raises(jsonschema.ValidationError):
        validate(view, cfg)
