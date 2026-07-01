"""Interactive 'Ingest candidate' route -- résumé upload + GitHub + note fusion."""

import importlib
import os
import tempfile

import pytest


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["TRANSFORMER_DB"] = tmp.name
    import app as app_module
    importlib.reload(app_module)
    # Mock the live GitHub call so the test is offline + deterministic.
    from transformer.sources import github_source
    monkeypatch.setattr(
        github_source, "_http_get_json",
        lambda url, params=None: (
            {"name": "Mona", "html_url": "https://github.com/octocat"} if url.endswith("/users/octocat")
            else ([{"language": "Ruby"}] if "repos" in url else None)
        ),
    )
    with app_module.app.test_client() as c:
        yield c, app_module
    app_module.REPO.close()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def test_ingest_candidate_fuses_resume_github_note(client):
    c, app_module = client
    data = {
        "resume": (open("samples/resumes/jane_doe.pdf", "rb"), "jane_doe.pdf"),
        "github": "octocat",
        "note": "Reachable at jane.doe@example.com; strong candidate.",
    }
    r = c.post("/ingest-candidate", data=data, content_type="multipart/form-data")
    assert r.status_code == 302
    cid = r.headers["Location"].split("/candidate/")[-1]
    rec = app_module.REPO.get(cid)
    sources = {p["source"] for p in rec["canonical"]["provenance"]}
    assert "resume" in sources          # uploaded file parsed
    assert "github" in sources          # live enrichment merged
    assert "Ruby" in {s["name"] for s in rec["canonical"]["skills"]}  # from GitHub repos


def test_ingest_empty_does_not_crash(client):
    c, _ = client
    r = c.post("/ingest-candidate", data={}, content_type="multipart/form-data")
    assert r.status_code == 302        # redirects back to dashboard, no error


def test_ingest_rejects_non_resume_extension(client):
    c, app_module = client
    before = app_module.REPO.count()
    data = {"resume": (open("samples/candidates.csv", "rb"), "candidates.csv")}
    r = c.post("/ingest-candidate", data=data, content_type="multipart/form-data")
    assert r.status_code == 302
    assert app_module.REPO.count() == before   # .csv ignored, nothing ingested
