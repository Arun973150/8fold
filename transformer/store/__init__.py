"""Persistence layer.

A SQLite-backed store that holds per-source records, blocking keys, recruiter
corrections, and the resolved canonical record per candidate. The Repository is
written against a narrow interface, so swapping SQLite for Postgres in production
is a backend change, not a rewrite (see the README roadmap).
"""

from .repository import Repository  # noqa: F401
