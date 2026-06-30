"""End-to-end orchestrator shared by the UI, the CLI, and the tests.

detect inputs -> run adapters -> cluster into candidates -> enrich each candidate
with a live GitHub fetch (if a handle was found) -> resolve -> project -> validate.

Per-candidate work is isolated: one bad candidate (e.g. a missing required field
under on_missing='error', or a schema violation) is recorded as an error and the
batch continues. A missing/garbage source never crashes the run.
"""

from __future__ import annotations

import os
from typing import List, Optional

from .model import SourceRecord
from .sources import csv_source, ats_source, notes_source, github_source, resume_source
from .normalize.emails import normalize_emails
from .merge.resolver import cluster, resolve
from .projection.project import project, ProjectionError
from .projection.validate import validate
from .trust.build import build_trust, DEFAULT_THRESHOLD


def _discover_inputs(inputs_dir: str) -> List[SourceRecord]:
    """Route every file under ``inputs_dir`` to the right adapter."""
    records: List[SourceRecord] = []
    if not os.path.isdir(inputs_dir):
        return records

    for name in sorted(os.listdir(inputs_dir)):
        path = os.path.join(inputs_dir, name)
        low = name.lower()
        if os.path.isdir(path):
            if low in ("notes", "recruiter_notes"):
                records += notes_source.load(path)
            elif low in ("resumes", "resume"):
                records += resume_source.load(path)
            continue
        if low.endswith(".csv"):
            records += csv_source.load(path)
        elif low.endswith(".json") and "config" not in low:
            records += ats_source.load(path)
        elif low.endswith(".txt"):
            records += notes_source.load(path)
        elif low.endswith((".pdf", ".docx")):
            records += resume_source.load(path)
    return records


def _github_handle(records: List[SourceRecord]) -> Optional[str]:
    """Find a github handle among a cluster's links."""
    for rec in records:
        links = rec.raw.get("links")
        if isinstance(links, dict) and links.get("github"):
            raw = str(links["github"]).strip().rstrip("/")
            if "github.com/" in raw:
                raw = raw.split("github.com/")[-1].split("/")[0]
            return raw.lstrip("@") or None
    return None


def _candidate_id(records: List[SourceRecord], index: int) -> str:
    emails = []
    for rec in records:
        emails += normalize_emails(rec.raw.get("emails"))
    if emails:
        return sorted(emails)[0]
    for rec in records:
        name = rec.raw.get("full_name")
        if isinstance(name, str) and name.strip():
            return name.strip().lower().replace(" ", "-")
    return f"candidate-{index}"


def run(
    inputs_dir: str,
    config: Optional[dict] = None,
    *,
    fetch_github: bool = True,
    trust: bool = False,
    review_threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """Process a directory of inputs into projected, validated profiles.

    Returns ``{"profiles": [...views...], "errors": [...]}``. When ``trust`` is
    set, also returns ``"trust"``: per-candidate quality/conflict reports with a
    field-level audit trail, plus a batch rollup and review queue.
    """
    records = _discover_inputs(inputs_dir)
    clusters = cluster(records)

    profiles = []
    resolved = []  # keep canonical Profiles for the trust layer
    errors = []
    for i, group in enumerate(clusters):
        try:
            if fetch_github:
                handle = _github_handle(group)
                if handle:
                    gh = github_source.fetch(handle)  # live, degrades to None on failure
                    if gh is not None:
                        group = group + [gh]

            cid = _candidate_id(group, i)
            profile = resolve(group, cid)
            view = project(profile, config)
            validate(view, config)
            profiles.append(view)
            resolved.append(profile)
        except ProjectionError as e:
            errors.append({"candidate_id": e.candidate_id, "error": str(e)})
        except Exception as e:  # noqa: BLE001 - isolate any candidate-level failure
            errors.append({"candidate_id": f"candidate-{i}", "error": repr(e)})

    result = {"profiles": profiles, "errors": errors}
    if trust:
        result["trust"] = build_trust(resolved, review_threshold)
    return result
