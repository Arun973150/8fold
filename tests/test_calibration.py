"""Self-calibrating trust: weight learning from override rates."""

import os

from transformer.store import Repository
from transformer.store.ingest import ingest_dir
from transformer.trust import calibration
from transformer.merge.confidence import SOURCE_WEIGHT, base_confidence
from transformer.model import SOURCE_ATS_JSON, METHOD_FIELD_MAP

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


def test_calibrated_weights_default_when_no_overrides():
    w = calibration.calibrated_weights({}, {})
    assert w == {s: round(b, 4) for s, b in SOURCE_WEIGHT.items()}


def test_calibrated_weight_drops_with_overrides():
    # 2 corrections against a source that contributed 4 records -> rate 0.5
    w = calibration.calibrated_weights({SOURCE_ATS_JSON: 2}, {SOURCE_ATS_JSON: 4})
    assert w[SOURCE_ATS_JSON] < SOURCE_WEIGHT[SOURCE_ATS_JSON]


def test_calibrated_weight_has_a_floor():
    # massive override rate still floored at 40% of base
    w = calibration.calibrated_weights({SOURCE_ATS_JSON: 100}, {SOURCE_ATS_JSON: 1})
    assert w[SOURCE_ATS_JSON] == round(SOURCE_WEIGHT[SOURCE_ATS_JSON] * 0.4, 4)


def test_base_confidence_respects_weight_override():
    default = base_confidence(SOURCE_ATS_JSON, METHOD_FIELD_MAP)
    lowered = base_confidence(SOURCE_ATS_JSON, METHOD_FIELD_MAP, {SOURCE_ATS_JSON: 0.5})
    assert lowered < default


def test_repository_learns_from_corrections():
    repo = Repository(":memory:", threshold=0.6)
    ingest_dir(repo, SAMPLES)
    assert repo._current_weights() is None             # no feedback yet -> defaults

    # Override an ATS-owned field -> ATS trust should drop.
    before = repo.get("jane.doe@example.com")["canonical"]["overall_confidence"]
    repo.add_correction("jane.doe@example.com", "headline", "Principal Engineer")
    rep = {r["source"]: r for r in repo.calibration_report()}
    assert rep[SOURCE_ATS_JSON]["overrides"] == 1
    assert rep[SOURCE_ATS_JSON]["calibrated_weight"] < rep[SOURCE_ATS_JSON]["base_weight"]

    # Reindexing applies the learned weight to everyone; Carlos (ATS-heavy) drops.
    carlos_before = repo.get("carlos.reyes@example.com")["canonical"]["overall_confidence"]
    repo.reindex()
    carlos_after = repo.get("carlos.reyes@example.com")["canonical"]["overall_confidence"]
    assert carlos_after <= carlos_before
