"""API smoke tests against an isolated in-memory-ish store."""

import os
import tempfile

import pytest


@pytest.fixture()
def client():
    # Point the service at a throwaway DB before importing it.
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["TRANSFORMER_DB"] = tmp.name
    import importlib
    import service as service_module
    importlib.reload(service_module)
    with service_module.app.test_client() as c:
        yield c
    service_module.repo.close()  # release the SQLite handle before deleting (Windows)
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def test_health_and_seed(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["candidates"] == 3   # auto-seeded from samples


def test_list_and_get(client):
    ids = [c["id"] for c in client.get("/candidates").get_json()]
    assert "jane.doe@example.com" in ids
    jane = client.get("/candidates/jane.doe@example.com").get_json()
    assert jane["canonical"]["full_name"] == "Jane A. Doe"
    assert "explain" in jane["trust"]


def test_ingest_then_override_persists(client):
    # ingest a new source for an existing person (shared email) -> still one candidate
    r = client.post("/ingest", json={
        "source": "ats_json",
        "raw": {"full_name": "Jane Updated", "emails": ["jane.doe@example.com"], "headline": "Principal Engineer"},
    })
    assert r.status_code == 200
    cid = r.get_json()["candidate_id"]
    assert cid == "jane.doe@example.com"

    # override the name -> persists and wins
    r = client.post(f"/candidates/{cid}/override", json={"field": "full_name", "value": "Jane Corrected"})
    assert r.get_json()["canonical"]["full_name"] == "Jane Corrected"


def test_projection_endpoint(client):
    cfg = {"fields": [
        {"path": "full_name", "type": "string", "required": True},
        {"path": "primary_email", "from": "emails[0]", "type": "string"},
    ], "on_missing": "null"}
    r = client.post("/candidates/carlos.reyes@example.com/projection", json=cfg)
    assert r.status_code == 200
    body = r.get_json()
    assert body["full_name"] == "Carlos Reyes"
    assert body["primary_email"] == "carlos.reyes@example.com"


def test_review_queue_endpoint(client):
    q = {c["id"] for c in client.get("/review-queue").get_json()}
    assert "sam-lee" in q
    assert "carlos.reyes@example.com" in q   # anomaly-flagged


def test_malformed_requests_return_client_errors(client):
    assert client.post("/ingest", json=[]).status_code == 400
    assert client.post("/ingest", json={"source": "ats_json", "raw": []}).status_code == 400
    assert client.post("/ingest/dir", json={"inputs": "../"}).status_code == 400
    bad = {"fields": [{"path": "x", "from": "bad path"}]}
    assert client.post("/candidates/jane.doe@example.com/projection", json=bad).status_code == 422
    assert client.post("/candidates/jane.doe@example.com/projection", json=[]).status_code == 400
