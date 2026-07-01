"""Repository: the stateful heart of the service.

Ingesting a source record runs incremental identity resolution (block -> score ->
link or create), stores the record + its blocking keys, then re-resolves ONLY the
affected candidate from its stored records plus any recruiter corrections. A new
source never reprocesses the world.

Recruiter corrections are stored and replayed as a SOURCE_OVERRIDE record, so they
flow through the same merge and -- being the most trusted source -- win.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from . import db
from ..model import SourceRecord, SOURCE_OVERRIDE, METHOD_HUMAN
from ..merge import identity
from ..merge.resolver import resolve
from ..trust.build import quality_report, explain
from ..trust import calibration


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, path: str = ":memory:", threshold: float = 0.6):
        self.conn = db.connect(path)
        self.threshold = threshold
        self._lock = threading.RLock()  # serialize writes across request threads

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------------ #
    # Ingestion + identity resolution
    # ------------------------------------------------------------------ #
    def ingest(self, record: SourceRecord, origin: str = None) -> str:
        """Ingest one source record.

        Idempotency has two modes:
        * no ``origin`` -> keyed by content hash (identical data is skipped).
        * with ``origin`` -> keyed by a stable logical id (e.g. a résumé filename or
          ``github:<handle>``). Re-ingesting the SAME source **refreshes it in place**
          instead of appending -- so re-uploading a résumé or re-fetching a GitHub
          profile (whose live/LLM output varies) never accumulates duplicates.
        """
        with self._lock:
            raw_json = json.dumps(record.raw, sort_keys=True, ensure_ascii=False)
            key = f"{record.source}|origin|{origin}" if origin else f"{record.source}|{raw_json}"
            sr_id = hashlib.sha1(key.encode("utf-8")).hexdigest()
            keys = identity.blocking_keys(record)

            existing = self.conn.execute(
                "SELECT candidate_id FROM source_record WHERE id=?", (sr_id,)
            ).fetchone()
            if existing:
                cid = existing["candidate_id"]
                if origin:  # same logical source -> refresh its content, re-resolve
                    self.conn.execute(
                        "UPDATE source_record SET raw_json=?, methods_json=?, ingested_at=? WHERE id=?",
                        (raw_json, json.dumps(record.methods), _now(), sr_id),
                    )
                    self._rebuild_keys(cid)
                    self.conn.commit()
                    self._resolve_and_save(cid)
                return cid  # (no origin: identical content, nothing to do)

            cid = self._match_or_create(record, keys)
            self.conn.execute(
                "INSERT INTO source_record(id,candidate_id,source,raw_json,methods_json,ingested_at)"
                " VALUES (?,?,?,?,?,?)",
                (sr_id, cid, record.source, raw_json, json.dumps(record.methods), _now()),
            )
            self._save_keys(cid, keys)
            self.conn.commit()
            self._resolve_and_save(cid)
            return cid

    def delete(self, cid: str) -> None:
        """Remove a candidate and everything derived from it."""
        with self._lock:
            self.conn.execute("DELETE FROM source_record WHERE candidate_id=?", (cid,))
            self.conn.execute("DELETE FROM candidate_key WHERE candidate_id=?", (cid,))
            self.conn.execute("DELETE FROM correction WHERE candidate_id=?", (cid,))
            self.conn.execute("DELETE FROM candidate WHERE id=?", (cid,))
            self.conn.commit()

    def _match_or_create(self, record: SourceRecord, keys: List[Tuple[str, str]]) -> str:
        candidate_ids = self._find_candidates_by_keys(keys)
        best_id, best = None, 0.0
        for c in sorted(candidate_ids):  # deterministic
            s = identity.score(self._candidate_keys(c), keys)
            if s > best:
                best, best_id = s, c
        if best_id is not None and best >= identity.LINK_THRESHOLD:
            return best_id
        return self._new_id(keys)

    def _find_candidates_by_keys(self, keys) -> set:
        ids = set()
        for t, v in keys:
            for row in self.conn.execute(
                "SELECT candidate_id FROM candidate_key WHERE key_type=? AND key_value=?", (t, v)
            ):
                ids.add(row["candidate_id"])
        return ids

    def _candidate_keys(self, cid: str) -> List[Tuple[str, str]]:
        return [
            (r["key_type"], r["key_value"])
            for r in self.conn.execute(
                "SELECT key_type,key_value FROM candidate_key WHERE candidate_id=?", (cid,)
            )
        ]

    def _new_id(self, keys) -> str:
        emails = sorted(v for t, v in keys if t == "email")
        if emails:
            base = emails[0]
        else:
            name = identity.name_of(keys)
            base = name.replace(" ", "-") if name else "candidate"
        cid, i = base, 2
        while self.conn.execute("SELECT 1 FROM candidate WHERE id=?", (cid,)).fetchone():
            cid, i = f"{base}-{i}", i + 1
        return cid

    def _save_keys(self, cid: str, keys):
        for t, v in keys:
            self.conn.execute(
                "INSERT OR IGNORE INTO candidate_key(key_type,key_value,candidate_id) VALUES (?,?,?)",
                (t, v, cid),
            )

    def _rebuild_keys(self, cid: str):
        """Replace derived keys after an origin-backed source refresh."""
        self.conn.execute("DELETE FROM candidate_key WHERE candidate_id=?", (cid,))
        for stored in self._records_for(cid):
            self._save_keys(cid, identity.blocking_keys(stored))

    # ------------------------------------------------------------------ #
    # Re-resolution
    # ------------------------------------------------------------------ #
    def _records_for(self, cid: str) -> List[SourceRecord]:
        out = []
        for r in self.conn.execute(
            "SELECT source,raw_json,methods_json FROM source_record WHERE candidate_id=? ORDER BY id", (cid,)
        ):
            out.append(SourceRecord(r["source"], json.loads(r["raw_json"]), json.loads(r["methods_json"])))
        return out

    def _corrections_for(self, cid: str) -> dict:
        return {
            r["field"]: r["value"]
            for r in self.conn.execute(
                "SELECT field,value FROM correction WHERE candidate_id=?", (cid,)
            )
        }

    def _override_record(self, corrections: dict) -> Optional[SourceRecord]:
        if not corrections:
            return None
        raw, methods = {}, {}
        for field, value in corrections.items():
            if field == "years_experience":
                try:
                    raw[field] = float(value)
                except (TypeError, ValueError):
                    continue
            elif field in ("emails", "phones"):
                raw[field] = [value]
            else:
                raw[field] = value
            methods[field] = METHOD_HUMAN
        return SourceRecord(SOURCE_OVERRIDE, raw, methods) if raw else None

    def _resolve_and_save(self, cid: str):
        records = self._records_for(cid)
        override = self._override_record(self._corrections_for(cid))
        if override:
            records = records + [override]
        profile = resolve(records, cid, weights=self._current_weights())
        report = quality_report(profile, self.threshold)
        report["explain"] = explain(profile)

        row = self.conn.execute("SELECT status FROM candidate WHERE id=?", (cid,)).fetchone()
        if row and row["status"] == "reviewed":
            status = "reviewed"  # a human sign-off is sticky
        else:
            status = "needs_review" if report["needs_review"] else "accepted"

        self.conn.execute(
            "INSERT INTO candidate(id,canonical_json,trust_json,overall_confidence,status,updated_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET canonical_json=excluded.canonical_json,"
            " trust_json=excluded.trust_json, overall_confidence=excluded.overall_confidence,"
            " status=excluded.status, updated_at=excluded.updated_at",
            (cid, json.dumps(profile.to_dict()), json.dumps(report),
             profile.overall_confidence, status, _now()),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ #
    # Recruiter actions
    # ------------------------------------------------------------------ #
    def add_correction(self, cid: str, field: str, value):
        with self._lock:
            # Attribute the correction to whichever source currently owns this field,
            # so self-calibration can learn that source is less reliable here.
            displaced = self._winner_source(cid, field)
            weights_changed = bool(displaced and displaced != SOURCE_OVERRIDE)
            if weights_changed:
                self.conn.execute(
                    "INSERT INTO source_stat(source,overrides) VALUES (?,1)"
                    " ON CONFLICT(source) DO UPDATE SET overrides=overrides+1",
                    (displaced,),
                )

            self.conn.execute(
                "INSERT INTO correction(candidate_id,field,value,created_at) VALUES (?,?,?,?)"
                " ON CONFLICT(candidate_id,field) DO UPDATE SET value=excluded.value, created_at=excluded.created_at",
                (cid, field, str(value), _now()),
            )
            self.conn.commit()
            if weights_changed:
                # Source weights are global, so keep every stored profile current.
                self.reindex()
            else:
                self._resolve_and_save(cid)

    def set_status(self, cid: str, status: str):
        with self._lock:
            self.conn.execute("UPDATE candidate SET status=? WHERE id=?", (status, cid))
            self.conn.commit()

    def reindex(self, threshold: Optional[float] = None):
        with self._lock:
            if threshold is not None:
                self.threshold = threshold
            ids = [row["id"] for row in self.conn.execute("SELECT id FROM candidate")]
            for cid in ids:
                self._resolve_and_save(cid)

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM candidate").fetchone()["n"]

    def get(self, cid: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT canonical_json,trust_json,status FROM candidate WHERE id=?", (cid,)
        ).fetchone()
        if not row:
            return None
        return {
            "canonical": json.loads(row["canonical_json"]),
            "trust": json.loads(row["trust_json"]),
            "status": row["status"],
        }

    def list_candidates(self) -> List[dict]:
        out = []
        for row in self.conn.execute(
            "SELECT id,canonical_json,trust_json,overall_confidence,status FROM candidate ORDER BY id"
        ):
            canonical = json.loads(row["canonical_json"])
            trust = json.loads(row["trust_json"])
            out.append({
                "id": row["id"],
                "name": canonical.get("full_name") or row["id"],
                "status": row["status"],
                "overall_confidence": row["overall_confidence"],
                "completeness": trust.get("completeness"),
                "conflicts": len(trust.get("conflicts", [])),
                "flags": trust.get("flags", []),
            })
        return out

    def review_queue(self) -> List[dict]:
        return [c for c in self.list_candidates() if c["status"] == "needs_review"]

    def corrections(self, cid: str) -> dict:
        return self._corrections_for(cid)

    # ------------------------------------------------------------------ #
    # Self-calibrating trust
    # ------------------------------------------------------------------ #
    def _winner_source(self, cid: str, field: str) -> Optional[str]:
        rec = self.get(cid)
        if not rec:
            return None
        dec = rec["trust"].get("explain", {}).get(field)
        if not dec:
            return None
        for c in dec.get("considered", []):
            if c.get("won") and c.get("source"):
                return c["source"]
        for c in dec.get("considered", []):
            if c.get("source"):
                return c["source"]
        return None

    def _overrides(self) -> dict:
        return {
            r["source"]: r["overrides"]
            for r in self.conn.execute("SELECT source,overrides FROM source_stat")
        }

    def _exposure(self) -> dict:
        """How many records each source has contributed (a stable denominator).

        Using records-contributed (not fields-currently-won) keeps the override
        rate stable as winners flip, avoids a feedback loop, and is a single cheap
        GROUP BY -- so it scales.
        """
        return {
            r["source"]: r["n"]
            for r in self.conn.execute(
                "SELECT source, COUNT(*) AS n FROM source_record GROUP BY source"
            )
        }

    def _current_weights(self) -> Optional[dict]:
        overrides = self._overrides()
        if not overrides:
            return None  # no feedback yet -> static defaults, no extra work
        return calibration.calibrated_weights(overrides, self._exposure())

    def calibration_report(self) -> list:
        return calibration.report(self._overrides(), self._exposure())
