"""JSON HTTP API over the stateful store.

Event-driven ingestion instead of a folder scan: POST a source record, the service
runs incremental identity resolution and re-resolves just that candidate. Reads
return the canonical record + trust report; overrides persist as corrections that
win on the next re-resolve.

Run:  python service.py            ->  http://127.0.0.1:5001
Env:  TRANSFORMER_DB (default candidates.db), REVIEW_THRESHOLD (default 0.6)
"""

from __future__ import annotations

import os

from flask import Flask, request, jsonify

from transformer.store import Repository
from transformer.store.ingest import ingest_dir, ensure_seeded
from transformer.model import SourceRecord
from transformer.projection.project import project_root, ProjectionError
from transformer.projection.validate import validate

DB_PATH = os.environ.get("TRANSFORMER_DB", "candidates.db")
THRESHOLD = float(os.environ.get("REVIEW_THRESHOLD", "0.6"))

repo = Repository(DB_PATH, threshold=THRESHOLD)
ensure_seeded(repo, "samples", fetch_github=False)

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok", candidates=repo.count(), threshold=repo.threshold)


@app.post("/ingest")
def ingest_one():
    """Ingest a single source record: {source, raw, methods?}."""
    body = request.get_json(force=True, silent=True) or {}
    if "source" not in body or "raw" not in body:
        return jsonify(error="body requires 'source' and 'raw'"), 400
    rec = SourceRecord(body["source"], body["raw"], body.get("methods", {}))
    cid = repo.ingest(rec)
    return jsonify(candidate_id=cid, status=repo.get(cid)["status"])


@app.post("/ingest/dir")
def ingest_directory():
    body = request.get_json(force=True, silent=True) or {}
    n = ingest_dir(repo, body.get("inputs", "samples"), bool(body.get("fetch_github")))
    return jsonify(count=n)


@app.get("/candidates")
def list_candidates():
    return jsonify(repo.list_candidates())


@app.get("/review-queue")
def review_queue():
    return jsonify(repo.review_queue())


@app.get("/calibration")
def calibration():
    """Per-source learned trust: base weight vs weight calibrated from override rates."""
    return jsonify(repo.calibration_report())


@app.get("/candidates/<path:cid>")
def get_candidate(cid):
    rec = repo.get(cid)
    if rec is None:
        return jsonify(error="not found"), 404
    return jsonify(rec)


@app.post("/candidates/<path:cid>/projection")
def project_candidate(cid):
    rec = repo.get(cid)
    if rec is None:
        return jsonify(error="not found"), 404
    config = request.get_json(force=True, silent=True)
    try:
        view = project_root(rec["canonical"], config)
        validate(view, config)
    except ProjectionError as e:
        return jsonify(error=str(e)), 422
    return jsonify(view)


@app.post("/candidates/<path:cid>/override")
def override_candidate(cid):
    if repo.get(cid) is None:
        return jsonify(error="not found"), 404
    body = request.get_json(force=True, silent=True) or {}
    if "field" not in body or "value" not in body:
        return jsonify(error="body requires 'field' and 'value'"), 400
    repo.add_correction(cid, body["field"], body["value"])
    return jsonify(repo.get(cid))


@app.post("/candidates/<path:cid>/review")
def review_candidate(cid):
    if repo.get(cid) is None:
        return jsonify(error="not found"), 404
    repo.set_status(cid, "reviewed")
    return jsonify(status="reviewed")


if __name__ == "__main__":
    app.run(port=5001, debug=True)
