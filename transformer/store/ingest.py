"""Ingest a directory of sources into a Repository (incremental, idempotent).

Each source record is ingested individually so identity resolution links it to the
right candidate. If ``fetch_github`` is set, a discovered handle is fetched live and
ingested too (it links by its github key). Re-running is a no-op (content-hash
idempotency), which is exactly how a periodic sync would behave.
"""

from __future__ import annotations

from .repository import Repository
from ..pipeline import _discover_inputs, _github_handle
from ..sources import github_source


def ingest_dir(repo: Repository, inputs_dir: str, fetch_github: bool = False) -> int:
    for record in _discover_inputs(inputs_dir):
        repo.ingest(record)
        if fetch_github:
            handle = _github_handle([record])
            if handle:
                gh = github_source.fetch(handle)
                if gh is not None:
                    repo.ingest(gh)
    return repo.count()


def ensure_seeded(repo: Repository, inputs_dir: str, fetch_github: bool = False) -> int:
    """Ingest ``inputs_dir`` only if the store is empty (first-run convenience)."""
    if repo.count() == 0:
        ingest_dir(repo, inputs_dir, fetch_github)
    return repo.count()
