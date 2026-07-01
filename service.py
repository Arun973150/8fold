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

import jsonschema
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


def _json_object():
    body = request.get_json(force=True, silent=True)
    return body if isinstance(body, dict) else None


def _safe_input_dir(value):
    """Allow directory ingestion only from inside this project workspace."""
    if not isinstance(value, str) or not value.strip():
        return None
    root = os.path.realpath(os.path.dirname(__file__))
    target = os.path.realpath(os.path.join(root, value))
    try:
        return target if os.path.commonpath([root, target]) == root else None
    except ValueError:
        return None


@app.get("/health")
def health():
    return jsonify(status="ok", candidates=repo.count(), threshold=repo.threshold)


@app.post("/ingest")
def ingest_one():
    """Ingest a single source record: {source, raw, methods?}."""
    body = _json_object()
    if body is None:
        return jsonify(error="body must be a JSON object"), 400
    if not isinstance(body.get("source"), str) or not body["source"].strip():
        return jsonify(error="'source' must be a non-empty string"), 400
    if not isinstance(body.get("raw"), dict):
        return jsonify(error="'raw' must be an object"), 400
    if "methods" in body and not isinstance(body["methods"], dict):
        return jsonify(error="'methods' must be an object"), 400
    rec = SourceRecord(body["source"], body["raw"], body.get("methods", {}))
    cid = repo.ingest(rec)
    return jsonify(candidate_id=cid, status=repo.get(cid)["status"])


@app.post("/ingest/dir")
def ingest_directory():
    body = _json_object()
    if body is None:
        return jsonify(error="body must be a JSON object"), 400
    inputs = _safe_input_dir(body.get("inputs", "samples"))
    if inputs is None or not os.path.isdir(inputs):
        return jsonify(error="'inputs' must be a directory inside the project workspace"), 400
    n = ingest_dir(repo, inputs, bool(body.get("fetch_github")))
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


@app.delete("/candidates/<path:cid>")
def delete_candidate(cid):
    if repo.get(cid) is None:
        return jsonify(error="not found"), 404
    repo.delete(cid)
    return jsonify(deleted=cid)


@app.post("/candidates/<path:cid>/projection")
def project_candidate(cid):
    rec = repo.get(cid)
    if rec is None:
        return jsonify(error="not found"), 404
    config = _json_object()
    if config is None:
        return jsonify(error="body must be a projection config object"), 400
    try:
        view = project_root(rec["canonical"], config)
        validate(view, config)
    except (ProjectionError, ValueError, KeyError, TypeError, jsonschema.ValidationError) as e:
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
    # debug off by default (Werkzeug debugger = RCE risk); FLASK_DEBUG=1 to enable.
    app.run(port=5001, debug=os.environ.get("FLASK_DEBUG") == "1")
