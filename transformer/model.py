"""Internal data model and the default canonical JSON schema.

Two layers live here:

* ``SourceRecord`` -- a raw-but-tagged record from one source; what adapters emit
  and the merge stage consumes.
* ``Profile`` -- the canonical record (full fixed schema). This is the internal
  representation; the projection layer derives every output *view* from it.

Keeping the canonical record separate from any output shape is the central design
decision: the engine never changes, only the projection does.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

# Stable identifiers for every source we support. Used in provenance and in the
# deterministic confidence weight tables (see merge/confidence.py).
SOURCE_RECRUITER_CSV = "recruiter_csv"
SOURCE_ATS_JSON = "ats_json"
SOURCE_GITHUB = "github"
SOURCE_RECRUITER_NOTES = "recruiter_notes"
SOURCE_RESUME = "resume"  # PDF / DOCX prose; free-text tier of trust
# A recruiter's explicit correction. Persisted as a source so it flows through the
# same merge path and -- being the most trusted -- wins on re-resolve.
SOURCE_OVERRIDE = "recruiter_override"

# Extraction methods, ordered loosely by how much we trust the extraction itself.
METHOD_FIELD_MAP = "field_map"   # came from a labelled column / key
METHOD_API = "api"               # structured API response
METHOD_REGEX = "regex"           # pulled out of free text with a pattern
METHOD_HUMAN = "human"           # a person entered/confirmed it


@dataclass
class SourceRecord:
    """A single candidate's worth of raw fields from one source.

    ``raw`` is keyed by *canonical* field names -- each adapter is responsible for
    mapping its own vocabulary (e.g. the ATS blob's names) onto ours. Values are
    still raw (un-normalized); normalization is a separate, centralized pass.
    """

    source: str
    raw: dict
    methods: dict = field(default_factory=dict)  # canonical field -> METHOD_*

    def method_for(self, canonical_field: str) -> str:
        return self.methods.get(canonical_field, METHOD_FIELD_MAP)


@dataclass
class Profile:
    """The canonical candidate record -- always the full fixed schema."""

    candidate_id: str
    full_name: Optional[str] = None
    emails: list = field(default_factory=list)
    phones: list = field(default_factory=list)
    location: dict = field(default_factory=lambda: {"city": None, "region": None, "country": None})
    links: dict = field(default_factory=lambda: {"linkedin": None, "github": None, "portfolio": None, "other": []})
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list = field(default_factory=list)        # [{name, confidence, sources[]}]
    experience: list = field(default_factory=list)    # [{company, title, start, end, summary}]
    education: list = field(default_factory=list)      # [{institution, degree, field, end_year}]
    provenance: list = field(default_factory=list)     # [{field, source, method}]
    overall_confidence: float = 0.0
    # Internal-only bookkeeping, surfaced through the trust layer, never part of
    # the canonical output schema.
    field_confidence: dict = field(default_factory=dict)
    trace: dict = field(default_factory=dict)  # field -> decision (winner + losers + reason)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("field_confidence", None)  # internal bookkeeping, not part of the schema
        d.pop("trace", None)
        return d


# Date strings are "YYYY-MM" when the month is known, or "YYYY" when only the year
# is. We deliberately do NOT invent a month -- inventing would violate the
# "never-invent" rule -- so the pattern accepts both forms.
DATE_PATTERN = r"^\d{4}(-(0[1-9]|1[0-2]))?$"

# The default canonical schema. The projection layer validates against this when
# no custom config is supplied.
DEFAULT_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["candidate_id", "full_name", "emails", "phones"],
    "properties": {
        "candidate_id": {"type": "string"},
        "full_name": {"type": ["string", "null"]},
        "emails": {"type": "array", "items": {"type": "string"}},
        "phones": {"type": "array", "items": {"type": "string"}},
        "location": {
            "type": "object",
            "properties": {
                "city": {"type": ["string", "null"]},
                "region": {"type": ["string", "null"]},
                "country": {"type": ["string", "null"]},
            },
        },
        "links": {
            "type": "object",
            "properties": {
                "linkedin": {"type": ["string", "null"]},
                "github": {"type": ["string", "null"]},
                "portfolio": {"type": ["string", "null"]},
                "other": {"type": "array", "items": {"type": "string"}},
            },
        },
        "headline": {"type": ["string", "null"]},
        "years_experience": {"type": ["number", "null"]},
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "confidence": {"type": "number"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "start": {"type": ["string", "null"], "pattern": DATE_PATTERN},
                    "end": {"type": ["string", "null"], "pattern": DATE_PATTERN},
                    "summary": {"type": ["string", "null"]},
                },
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": ["string", "null"]},
                    "degree": {"type": ["string", "null"]},
                    "field": {"type": ["string", "null"]},
                    "end_year": {"type": ["integer", "null"]},
                },
            },
        },
        "provenance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "source": {"type": "string"},
                    "method": {"type": "string"},
                },
            },
        },
        "overall_confidence": {"type": "number"},
    },
}
