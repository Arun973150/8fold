"""Store + incremental identity resolution + correction-wins tests."""

import os

from transformer.store import Repository
from transformer.store.ingest import ingest_dir
from transformer.model import (
    SourceRecord, SOURCE_ATS_JSON, SOURCE_RECRUITER_CSV, SOURCE_RECRUITER_NOTES,
    SOURCE_GITHUB, METHOD_API,
)
from transformer.merge import identity

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


def test_reingest_with_origin_refreshes_without_duplicates():
    repo = Repository(":memory:")
    cid = repo.ingest(SourceRecord(SOURCE_GITHUB, {"full_name": "void", "emails": ["a@b.com"]},
                                   {"full_name": METHOD_API}), origin="github:me")
    # same logical source, changed content -> replaces in place
    cid2 = repo.ingest(SourceRecord(SOURCE_GITHUB, {"full_name": "Arun N", "emails": ["a@b.com"]},
                                    {"full_name": METHOD_API}), origin="github:me")
    assert cid == cid2
    n = repo.conn.execute("SELECT COUNT(*) AS c FROM source_record WHERE candidate_id=?", (cid,)).fetchone()["c"]
    assert n == 1                                          # not duplicated
    assert repo.get(cid)["canonical"]["full_name"] == "Arun N"   # refreshed to latest


def test_origin_refresh_removes_stale_identity_keys():
    repo = Repository(":memory:")
    cid = repo.ingest(SourceRecord(SOURCE_ATS_JSON,
                                   {"full_name": "Alice One", "emails": ["old@example.com"]}),
                      origin="ats:1")
    repo.ingest(SourceRecord(SOURCE_ATS_JSON,
                             {"full_name": "Alice One", "emails": ["new@example.com"]}),
                origin="ats:1")
    assert ("email", "old@example.com") not in repo._candidate_keys(cid)
    other = repo.ingest(SourceRecord(SOURCE_RECRUITER_CSV,
                                     {"full_name": "Different Person",
                                      "emails": ["old@example.com"]}))
    assert other != cid


def test_delete_removes_candidate_and_records():
    repo = Repository(":memory:")
    ingest_dir(repo, SAMPLES)
    repo.delete("sam-lee")
    assert repo.get("sam-lee") is None
    assert "sam-lee" not in {c["id"] for c in repo.list_candidates()}
    assert repo.conn.execute("SELECT COUNT(*) AS c FROM source_record WHERE candidate_id=?",
                             ("sam-lee",)).fetchone()["c"] == 0


def test_ingest_clusters_and_is_idempotent():
    repo = Repository(":memory:", threshold=0.6)
    ingest_dir(repo, SAMPLES)
    assert repo.count() == 3                  # Jane, Carlos, Sam merged across sources
    ingest_dir(repo, SAMPLES)                 # re-ingest
    assert repo.count() == 3                  # idempotent, no duplicates


def test_incremental_link_by_shared_email():
    repo = Repository(":memory:")
    a = repo.ingest(SourceRecord(SOURCE_RECRUITER_CSV, {"full_name": "Jane Doe", "emails": ["jane@x.com"]}))
    b = repo.ingest(SourceRecord(SOURCE_ATS_JSON, {"full_name": "Jane A. Doe", "emails": ["jane@x.com"]}))
    assert a == b                             # same person, one candidate
    assert repo.count() == 1


def test_distinct_people_stay_separate():
    repo = Repository(":memory:")
    repo.ingest(SourceRecord(SOURCE_RECRUITER_CSV, {"full_name": "Jane Doe", "emails": ["jane@x.com"]}))
    repo.ingest(SourceRecord(SOURCE_ATS_JSON, {"full_name": "Bob Smith", "emails": ["bob@x.com"]}))
    assert repo.count() == 2


def test_identity_score_strong_vs_name():
    j1 = [("email", "a@b.com"), ("name", "jane doe")]
    j2 = [("email", "a@b.com"), ("name", "jane a doe")]
    assert identity.score(j1, j2) == 1.0      # shared email -> certain
    n1 = [("name", "jonathan smith")]
    n2 = [("name", "jonathan smith")]
    assert identity.score(n1, n2) >= 0.9      # identical name links
    assert identity.score([("name", "alice")], [("name", "bob")]) == 0.0
    assert identity.score([("email", "a@x.com"), ("name", "sam lee")],
                          [("email", "b@x.com"), ("name", "sam lee")]) == 0.0


def test_correction_wins_and_review_is_sticky():
    repo = Repository(":memory:", threshold=0.6)
    ingest_dir(repo, SAMPLES)
    repo.add_correction("jane.doe@example.com", "full_name", "Jane Q. Public")
    assert repo.get("jane.doe@example.com")["canonical"]["full_name"] == "Jane Q. Public"

    repo.set_status("sam-lee", "reviewed")
    repo.reindex(0.6)                          # re-resolve everything
    assert repo.get("sam-lee")["status"] == "reviewed"   # human sign-off persists


def test_review_queue_flags_sparse_and_anomalous():
    repo = Repository(":memory:", threshold=0.6)
    ingest_dir(repo, SAMPLES)
    queue = {c["id"] for c in repo.review_queue()}
    assert "sam-lee" in queue                              # sparse / no email
    assert "carlos.reyes@example.com" in queue            # anomaly: future grad year
