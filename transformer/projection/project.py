"""Apply a runtime output config to a canonical Profile.

The config can: select a subset of fields, remap a field from a canonical path
(``from``), re-normalize a field at projection time, toggle confidence/provenance,
and decide what happens when a value is missing (null / omit / error). The engine
is untouched -- this is pure projection over the canonical record.
"""

from __future__ import annotations

from typing import Any, Optional

from ..model import Profile
from ..normalize.phones import normalize_phone
from ..normalize.skills import normalize_skill
from .paths import resolve_path


class ProjectionError(Exception):
    """Raised when a required/any value is missing under on_missing='error'."""

    def __init__(self, output_key: str, source_path: str, candidate_id: str):
        self.output_key = output_key
        self.source_path = source_path
        self.candidate_id = candidate_id
        super().__init__(
            f"missing value for '{output_key}' (from '{source_path}') "
            f"on candidate '{candidate_id}'"
        )


_PROJECTION_NORMALIZERS = {
    "E164": lambda v: normalize_phone(v) if isinstance(v, str) else v,
    "canonical": lambda v: (
        [normalize_skill(x) for x in v if normalize_skill(x)]
        if isinstance(v, list) else normalize_skill(v)
    ),
}


def _apply_normalize(value: Any, name: Optional[str]) -> Any:
    if name is None or value is None:
        return value
    fn = _PROJECTION_NORMALIZERS.get(name)
    return fn(value) if fn else value


def project(profile: Profile, config: Optional[dict]) -> dict:
    """Project a Profile under ``config`` (None -> full canonical record)."""
    return project_root(profile.to_dict(), config)


def project_root(root: dict, config: Optional[dict]) -> dict:
    """Project from a canonical *dict* (e.g. one loaded from the store).

    ``root`` is the full canonical record, so ``overall_confidence`` and
    ``provenance`` are read from it directly. None config returns it unchanged.
    """
    if config is None:
        return root

    candidate_id = root.get("candidate_id", "?")
    on_missing = config.get("on_missing", "null")
    out: dict = {}

    for field in config.get("fields", []):
        out_key = field["path"]
        source_path = field.get("from", field["path"])
        found, value = resolve_path(root, source_path)

        if not found or value is None or value == []:
            if on_missing == "error":
                raise ProjectionError(out_key, source_path, candidate_id)
            if on_missing == "omit":
                continue
            out[out_key] = None
            continue

        value = _apply_normalize(value, field.get("normalize"))
        # A normalizer can fail a value back to None -> treat as missing too.
        if value is None:
            if on_missing == "error":
                raise ProjectionError(out_key, source_path, candidate_id)
            if on_missing == "omit":
                continue
            out[out_key] = None
            continue
        out[out_key] = value

    if config.get("include_confidence"):
        out["overall_confidence"] = root.get("overall_confidence", 0.0)
    if config.get("include_provenance"):
        out["provenance"] = root.get("provenance", [])
    return out
