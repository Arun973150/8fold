"""GitHub profile adapter (unstructured -> live public REST API).

Given a github handle (discovered from any other source's links), this fetches the
public user object and the public repo list, deriving: full_name, headline (bio),
portfolio + github links, location, and skills (the set of languages across the
user's repos).

Determinism note: the assignment asks for a deterministic pipeline, but a live
call cannot be byte-stable. We reconcile the two by (a) degrading gracefully --
any network error / rate-limit / missing user yields an empty record and never
crashes -- and (b) mocking ``_http_get_json`` in the test suite so tests run
offline and deterministically. Only the live CLI demo touches the network.
"""

from __future__ import annotations

from typing import List, Optional

import re

import requests

from ..model import SourceRecord, SOURCE_GITHUB, METHOD_API

API = "https://api.github.com"
TIMEOUT = 6  # seconds; short so a slow/blocked network does not stall a batch


def _http_get_json(url: str, params: Optional[dict] = None):
    """Single seam for all network I/O -- patched out in tests."""
    resp = requests.get(
        url,
        params=params,
        timeout=TIMEOUT,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "eightfold-transformer"},
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def _languages(handle: str) -> List[str]:
    repos = _http_get_json(f"{API}/users/{handle}/repos", params={"per_page": 100, "sort": "updated"})
    if not isinstance(repos, list):
        return []
    langs: List[str] = []
    for repo in repos:
        if isinstance(repo, dict) and repo.get("language"):
            lang = repo["language"]
            if lang not in langs:
                langs.append(lang)
    return langs


def fetch(handle: str) -> Optional[SourceRecord]:
    if not handle or not isinstance(handle, str):
        return None
    handle = handle.strip().lstrip("@")
    # Only real GitHub usernames (alnum + single hyphens, <=39) -- prevents a crafted
    # "handle" from a résumé/notes altering the request path.
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", handle):
        return None
    try:
        user = _http_get_json(f"{API}/users/{handle}")
    except requests.RequestException:
        return None
    if not isinstance(user, dict):
        return None

    raw = {}
    if user.get("name"):
        raw["full_name"] = user["name"]
    if user.get("bio"):
        raw["headline"] = user["bio"]
    if user.get("location"):
        raw["location"] = user["location"]
    if user.get("email"):
        raw["emails"] = [user["email"]]

    links = {"github": user.get("html_url") or f"https://github.com/{handle}"}
    if user.get("blog"):
        links["portfolio"] = user["blog"]
    raw["links"] = links

    try:
        skills = _languages(handle)
    except requests.RequestException:
        skills = []
    if skills:
        raw["skills"] = skills

    return SourceRecord(
        source=SOURCE_GITHUB,
        raw=raw,
        methods={k: METHOD_API for k in raw},
    )
