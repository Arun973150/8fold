"""Canonical-path resolver for the projection layer.

Supports the path grammar used by the custom-output config:

* ``full_name``            -> a top-level field
* ``location.country``     -> nested dict access
* ``emails[0]``            -> list index
* ``skills[].name``        -> map a sub-key across a list

Returns ``(found, value)``. ``found`` is False when any step is absent; callers
treat ``found=False`` or a ``None`` value as "missing" for on_missing handling.
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple

_STEP_RE = re.compile(r"^([A-Za-z0-9_]+)(\[\d+\]|\[\])?$")


def _parse(path: str) -> List[Tuple[str, Any]]:
    steps = []
    for seg in path.split("."):
        m = _STEP_RE.match(seg)
        if not m:
            raise ValueError(f"Invalid path segment: {seg!r} in {path!r}")
        key, mod = m.group(1), m.group(2)
        if mod is None:
            steps.append((key, None))
        elif mod == "[]":
            steps.append((key, ("map",)))
        else:
            steps.append((key, ("index", int(mod[1:-1]))))
    return steps


def _walk(value, steps):
    if not steps:
        return True, value
    (key, mod), rest = steps[0], steps[1:]
    if not isinstance(value, dict) or key not in value:
        return False, None
    value = value[key]
    if mod is None:
        return _walk(value, rest)
    if mod[0] == "index":
        idx = mod[1]
        if not isinstance(value, list) or idx >= len(value):
            return False, None
        return _walk(value[idx], rest)
    # map
    if not isinstance(value, list):
        return False, None
    results = []
    for item in value:
        ok, v = _walk(item, rest)
        if ok and v is not None:
            results.append(v)
    return True, results


def resolve_path(root: dict, path: str) -> Tuple[bool, Any]:
    return _walk(root, _parse(path))
