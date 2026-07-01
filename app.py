"""Recruiter review console -- store-backed.

The human-in-the-loop surface for the trust layer, now persistent. Candidates,
provenance, confidence, conflicts and corrections all come from the SQLite store
(transformer/store). An override is written as a recruiter correction and wins on
re-resolve, so the loop actually closes: the next time this candidate is touched,
the human's value stands.

Run:  python app.py   ->   http://127.0.0.1:5000
Env:  TRANSFORMER_DB (default candidates.db), REVIEW_THRESHOLD (default 0.6)
"""

from __future__ import annotations

import os

from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename

from transformer.store import Repository
from transformer.store.ingest import ingest_dir, ensure_seeded
from transformer.sources import resume_source, github_source, notes_source
from transformer.model import SourceRecord, SOURCE_RECRUITER_NOTES, METHOD_REGEX

DB_PATH = os.environ.get("TRANSFORMER_DB", "candidates.db")
SETTINGS = {"inputs": "samples", "threshold": float(os.environ.get("REVIEW_THRESHOLD", "0.6")),
            "fetch_github": False}
UPLOADS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB upload cap
REPO = Repository(DB_PATH, threshold=SETTINGS["threshold"])
ensure_seeded(REPO, SETTINGS["inputs"], SETTINGS["fetch_github"])

DISPLAY_ORDER = [
    "full_name", "headline", "years_experience", "emails", "phones",
    "location", "skills", "links", "experience", "education",
]


def conf_band(c):
    if c is None:
        return "na"
    return "high" if c >= 0.85 else ("mid" if c >= 0.6 else "low")


def _fmt(field, value):
    if value is None or value == [] or value == "":
        return "—"
    if field == "skills":
        return ", ".join(s["name"] for s in value)
    if field in ("emails", "phones"):
        return ", ".join(value)
    if field == "location":
        parts = [value.get("city"), value.get("region"), value.get("country")]
        return ", ".join(p for p in parts if p) or "—"
    if field == "links":
        items = [f"{k}: {v}" for k, v in value.items() if v and k != "other"]
        return " | ".join(items) or "—"
    if field == "experience":
        return [f"{e.get('title') or '?'} @ {e.get('company') or '?'} "
                f"({(e.get('start') or '?')}–{(e.get('end') or 'present')})" for e in value]
    if field == "education":
        return [f"{e.get('degree') or '?'} {e.get('field') or ''} — "
                f"{e.get('institution') or '?'} ({e.get('end_year') or '?'})" for e in value]
    return str(value)


def build_cards(canonical, report, corrections):
    explain = report.get("explain", {})
    cards = []
    for field in DISPLAY_ORDER:
        if field not in canonical:
            continue
        dec = explain.get(field)
        confidence = dec.get("confidence") if dec else None
        considered = dec.get("considered", []) if dec else []
        sources, seen = [], set()
        for c in considered:
            s = c.get("source")
            if s and s not in seen:
                seen.add(s); sources.append(s)
        conflict = bool(dec and dec.get("conflict"))
        options = [c for c in considered if "value" in c and "source" in c]
        cards.append({
            "field": field, "display": _fmt(field, canonical[field]),
            "confidence": confidence, "band": conf_band(confidence), "sources": sources,
            "conflict": conflict, "reason": dec.get("reason") if dec else None,
            "options": options if (len(options) > 1) else [],
            "overridden": field in corrections,
        })
    return cards


def batch_summary(cands):
    total = len(cands) or 1
    pending = sum(1 for c in cands if c["status"] == "needs_review")
    reviewed = sum(1 for c in cands if c["status"] == "reviewed")
    accepted = sum(1 for c in cands if c["status"] == "accepted")
    return {
        "total": len(cands), "pending": pending, "reviewed": reviewed, "accepted": accepted,
        "with_conflicts": sum(1 for c in cands if c["conflicts"] > 0),
        "avg_confidence": round(sum(c["overall_confidence"] for c in cands) / total, 3),
        "avg_completeness": round(sum((c["completeness"] or 0) for c in cands) / total, 3),
    }



@app.route("/", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        SETTINGS["inputs"] = request.form.get("inputs", "samples").strip() or "samples"
        try:
            SETTINGS["threshold"] = float(request.form.get("threshold", 0.6))
        except ValueError:
            pass
        SETTINGS["fetch_github"] = request.form.get("fetch_github") == "on"
        ingest_dir(REPO, SETTINGS["inputs"], SETTINGS["fetch_github"])
        REPO.reindex(SETTINGS["threshold"])
        return redirect(url_for("dashboard"))

    cands = REPO.list_candidates()
    rows = []
    for c in cands:
        conf = c["overall_confidence"] or 0
        rows.append({**c, "confpct": int(conf * 100), "band": conf_band(conf)})
    rows.sort(key=lambda r: (r["status"] != "needs_review", r["overall_confidence"]))
    return render_template("dashboard.html", s=SETTINGS, b=batch_summary(cands), rows=rows,
                           calibration=REPO.calibration_report())


@app.route("/candidate/<path:cid>")
def candidate(cid):
    rec = REPO.get(cid)
    if rec is None:
        return redirect(url_for("dashboard"))
    cards = build_cards(rec["canonical"], rec["trust"], REPO.corrections(cid))
    name = rec["canonical"].get("full_name") or cid
    return render_template("candidate.html", cid=cid, name=name, status=rec["status"],
                                  report=rec["trust"], cards=cards)


@app.route("/candidate/<path:cid>/override", methods=["POST"])
def override(cid):
    field = request.form.get("field")
    value = request.form.get("value")
    if field and value is not None:
        REPO.add_correction(cid, field, value)
    return redirect(url_for("candidate", cid=cid))


@app.route("/candidate/<path:cid>/review", methods=["POST"])
def review(cid):
    REPO.set_status(cid, "reviewed")
    return redirect(url_for("dashboard"))


@app.route("/ingest-candidate", methods=["POST"])
def ingest_candidate():
    """Interactive ingest: a résumé upload + optional GitHub handle + optional note,
    fused into one candidate and shown live."""
    # Each source is ingested with a stable ``origin`` so re-uploading the same
    # résumé / re-fetching the same GitHub profile refreshes it instead of piling
    # up duplicates.
    cids = []
    discovered_handle = None

    f = request.files.get("resume")
    if f and f.filename and f.filename.lower().endswith((".pdf", ".docx")):
        fname = secure_filename(f.filename)
        f.save(os.path.join(UPLOADS, fname))
        for rec in resume_source.load(os.path.join(UPLOADS, fname)):  # heuristic (+ LLM)
            tag = "-".join(sorted(set(rec.methods.values())))  # regex vs llm record
            cids.append(REPO.ingest(rec, origin=f"resume:{fname}:{tag}"))
            gh = (rec.raw.get("links") or {}).get("github")
            if gh and not discovered_handle:
                discovered_handle = str(gh).rstrip("/").split("/")[-1]

    note = (request.form.get("note") or "").strip()
    if note:
        raw = notes_source.parse_text(note)
        if raw:
            cids.append(REPO.ingest(SourceRecord(SOURCE_RECRUITER_NOTES, raw,
                                                 {k: METHOD_REGEX for k in raw})))

    # GitHub handle: typed wins, else the one discovered from a résumé hyperlink.
    handle = (request.form.get("github") or "").strip().lstrip("@") or discovered_handle
    if handle:
        gh_rec = github_source.fetch(handle)   # live, degrades to None
        if gh_rec:
            cids.append(REPO.ingest(gh_rec, origin=f"github:{handle.lower()}"))

    return redirect(url_for("candidate", cid=cids[0]) if cids else url_for("dashboard"))


@app.route("/candidate/<path:cid>/delete", methods=["POST"])
def delete_candidate(cid):
    REPO.delete(cid)
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    # debug is opt-in: the Werkzeug debugger allows code execution, so never on by
    # default. Enable locally with FLASK_DEBUG=1 if you want auto-reload.
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5000)


