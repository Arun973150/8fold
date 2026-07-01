# Multi-Source Candidate Data Transformer

Turns messy candidate data from many sources into **one clean, canonical profile
per candidate** — fixed fields, normalized formats, deduplicated across sources,
with **provenance** (where every value came from) and **confidence**.

Guiding rule: **wrong-but-confident is worse than honestly-empty.** Unknown or
unparseable values become `null` — they are never invented.

---

## Pipeline

```
inputs ─► detect/route ─► source adapters ─► normalize ─► merge & resolve ─► confidence
                                                                                  │
                                                          CANONICAL RECORD (internal, full schema)
                                                                                  │
                                                  projection (runtime config) ─► validate ─► output JSON
```

The key design decision is a **hard separation between the internal canonical
record and the output projection**. The engine always builds the full canonical
record; a runtime config only reshapes a *view* of it — same engine, no code
changes.

| Layer | Where |
|-------|-------|
| Source adapters (read + tag, no normalizing) | [transformer/sources/](transformer/sources/) |
| Normalizers (pure, total, never raise) | [transformer/normalize/](transformer/normalize/) |
| Cluster + conflict resolution | [transformer/merge/resolver.py](transformer/merge/resolver.py) |
| Deterministic confidence | [transformer/merge/confidence.py](transformer/merge/confidence.py) |
| Canonical model + default schema | [transformer/model.py](transformer/model.py) |
| Projection (config → view) + validation | [transformer/projection/](transformer/projection/) |
| **Trust layer** (explain / quality report / review gating) | [transformer/trust/](transformer/trust/) |
| **Store** (SQLite persistence + repository) | [transformer/store/](transformer/store/) |
| **Incremental identity resolution** (blocking + fuzzy) | [transformer/merge/identity.py](transformer/merge/identity.py) |
| Batch orchestrator | [transformer/pipeline.py](transformer/pipeline.py) |
| Review console (UI) · JSON API · CLI | [app.py](app.py) · [service.py](service.py) · [transformer/cli.py](transformer/cli.py) |

### Sources implemented (≥1 structured + ≥1 unstructured)

- **Structured:** Recruiter CSV export · ATS JSON blob (its own field names, mapped
  to ours via an explicit table in [ats_source.py](transformer/sources/ats_source.py)).
- **Unstructured:** GitHub public REST API (live) · recruiter notes `.txt` (regex) ·
  **résumés (`.pdf` / `.docx`)** parsed via pdfplumber / python-docx + heuristics.

### Normalized formats

phones → **E.164** (`phonenumbers`) · dates → **`YYYY-MM`** (or `YYYY`; we never
invent a month) · country → **ISO-3166 alpha-2** (`pycountry`) · skills →
**canonical names** (alias map + `rapidfuzz`) · emails → lowercased + deduped.

---

## Setup

```bash
pip install -r requirements.txt
# optional (LLM résumé extractor): cp .env.example .env and add GROQ_API_KEY
```

## Run — two modes

**Stateless batch** (engine over a folder → JSON) is the fastest way to see correctness.
**Stateful service** (SQLite store + identity resolution + API/console) is the
real-world shape. Both share the same engine.

### Review console (store-backed UI — primary surface)

```bash
python app.py
# open http://127.0.0.1:5000
```

A recruiter workflow, not a JSON viewer: an **"Add a candidate"** panel (upload a
résumé + GitHub handle + optional note → parse + live GitHub + LLM + merge → land on
the built profile), a **needs-review inbox**, per-field **provenance + color-coded
confidence**, **conflicts highlighted** with the alternatives, and **override /
mark-reviewed** actions. Overrides persist to the store as a recruiter correction and
**win on the next re-resolve** — the human-in-the-loop loop actually closes. (First
run auto-seeds from `samples/`.)

### JSON API (event-driven)

```bash
python service.py      # http://127.0.0.1:5001
# POST a source record and watch identity resolution + re-resolve:
curl -s localhost:5001/candidates | python -m json.tool
curl -s -X POST localhost:5001/ingest -H 'content-type: application/json' \
  -d '{"source":"ats_json","raw":{"full_name":"Jane X","emails":["jane.doe@example.com"]}}'
curl -s -X POST localhost:5001/candidates/jane.doe@example.com/override \
  -H 'content-type: application/json' -d '{"field":"full_name","value":"Jane Corrected"}'
```

Endpoints: `GET /candidates`, `GET /candidates/<id>`, `GET /review-queue`,
`GET /calibration`,
`POST /ingest`, `POST /candidates/<id>/projection`, `.../override`, `.../review`.

## Run — CLI

```bash
# default canonical schema
python -m transformer --inputs samples --out out/default_output.json

# a custom output config (the "twist")
python -m transformer --inputs samples --config samples/configs/custom.json \
    --out out/custom_output.json

# add --no-github to skip the live fetch (deterministic; used for the gold test)
```

Produced outputs are committed in [out/](out/):
[default_output.json](out/default_output.json) ·
[custom_output.json](out/custom_output.json).

---

## The runtime config (custom output)

Same engine, no code changes. A config can select a subset of fields, remap a
field from a canonical path (`from`), re-normalize at projection time, toggle
confidence/provenance, and choose `on_missing` = `null` | `omit` | `error`.

```json
{
  "fields": [
    { "path": "full_name", "type": "string", "required": true },
    { "path": "primary_email", "from": "emails[0]", "type": "string" },
    { "path": "phone", "from": "phones[0]", "type": "string", "normalize": "E164" },
    { "path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "on_missing": "null"
}
```

The path resolver supports `emails[0]`, `skills[].name`, and `location.country`.
Every projected view is **validated** against a JSON Schema derived from the
config before it is returned.

---

## Merge & confidence (deterministic)

- **Identity / match key:** shared normalized email, else shared normalized name
  (union-find). We do *not* fuzzily merge different names — documented limitation.
- **Scalar winner:** source reliability weight (ATS, CSV > GitHub > notes) ×
  extraction-method certainty; ties broken deterministically. **Every** contributing
  source is kept in `provenance`, even the losers.
- **Lists** (emails, phones, skills): unioned + deduped; skills corroborated by
  multiple sources rank higher.
- **Confidence** is a fixed function of weights — no randomness, no time, no
  network — so the same inputs always produce the same numbers.

---

## Trust Layer (beyond the spec)

The assignment gives us `provenance` and `confidence` as output fields — but says
nothing about *using* them. That's the gap we filled. The resolver retains **every**
proposal (winners *and* losers); the trust layer ([transformer/trust/](transformer/trust/))
turns that into:

- **Field-level "why" audit trail** — for each field: the chosen value, the
  alternatives it beat (with their sources/weights), whether a conflict fired, and a
  plain-English reason.
- **Data-quality / conflict report** — per candidate: completeness %, the exact
  fields where sources disagreed (with competing values), low-confidence fields, and
  data flags (`no_email`, `sparse`, …) — plus a **batch rollup**.
- **Review-queue gating** — a confidence/completeness threshold routes shaky
  profiles to `needs_review` with explicit reasons, instead of letting a
  wrong-but-confident profile enter hiring silently.
- **Anomaly detection** ([trust/anomalies.py](transformer/trust/anomalies.py)) — a
  data-quality signal *beyond* conflicts: implausible years of experience, future
  dates, inverted date ranges, and emails whose local-part doesn't match the name.
  Catches well-formed-but-wrong values even when every source agrees.
- **Self-calibrating trust** ([trust/calibration.py](transformer/trust/calibration.py))
  — source reliability **learns from feedback**: every recruiter override is counted
  against the source that supplied the value, and that source's weight is damped by its
  override rate (`base × max(floor, 1 − damping·rate)`). A source that's constantly
  corrected loses influence — the system improves as it's used. Visible on the dashboard
  and at `GET /calibration`.

```bash
python -m transformer --inputs samples --report out/trust_report.json --review-threshold 0.6
# -> 1 accepted, 2 need review (avg confidence 0.81, avg completeness 0.81)
```

See [out/trust_report.json](out/trust_report.json). Examples the sample data shows:
Jane's name conflict is surfaced ("Jane A. Doe" from ATS beat two "Jane Doe" sources,
penalized); **Carlos is flagged by anomaly detection** (a future graduation year, 2031 —
a data-entry error); Sam Lee is flagged (no email, low confidence, sparse). This is the
project's headline differentiator and the literal embodiment of *wrong-but-confident is
worse than honestly-empty*.

---

## Edge cases handled

1. **Conflicting scalars** (CSV "Acme" vs ATS "Acme Corp" / different titles) →
   weighted winner, both kept in provenance.
2. **Garbage input** (phone `not-a-number`, date `sometime 2021`, invalid
   `broken.json`) → value dropped / source skipped, run never crashes.
3. **Skill aliasing** (`reactjs`/`React.js`/`react` → `React`) → merged, confidence
   rises with corroboration.
4. **Missing required field** under `on_missing:"error"` (Sam Lee has no email) →
   structured per-candidate error; the rest of the batch still completes.
5. **Open-ended experience** (`to: present`) → `end: null`.
6. **GitHub handle unreachable** (the deliberately fake handle) → empty enrichment,
   profile still built from the other sources.

## Persistence, identity resolution & feedback loop

The stateful path ([transformer/store/](transformer/store/)) makes this a service, not
a one-shot script:

- **Storage (SQLite)** — per-source records, blocking keys, recruiter corrections, and
  the resolved canonical record per candidate. Schema is Postgres-portable.
- **Incremental identity resolution** — ingesting a record extracts **blocking keys**
  (email / phone / github, plus a weak name key), considers only candidates that share
  a key (no O(n²)), **scores** them (shared strong key ⇒ match; else conservative fuzzy
  name match), then **re-resolves only that one candidate** from its stored records.
  A new source never reprocesses the world. Idempotent by content hash.
- **Feedback loop** — a recruiter correction is stored and replayed as a
  `recruiter_override` source (the highest-trust source), so it flows through the same
  merge and **wins** on re-resolve. Human sign-off (`reviewed`) is sticky. Corrections
  also feed **self-calibrating trust** (above): the displaced source's reliability is
  learned down over time.

## Production roadmap (what real-world deployment still needs)

This take-home proves the model on SQLite; production at Eightfold scale would add:

- **Database:** PostgreSQL (`JSONB` canonical records, `pg_trgm`/`fuzzystrmatch` for
  fuzzy matching) as the system of record; a **blocking/search index**
  (OpenSearch or `pgvector` for embedding-based entity resolution) to dedup against
  millions; **Kafka** for event-driven ingestion instead of folder/HTTP.
- **Connectors:** OAuth, pagination, rate-limits, retries, incremental sync per source
  (LinkedIn has no public API — a compliance boundary, not a coding gap).
- **Privacy/compliance:** PII encryption, access control, consent, retention,
  right-to-be-forgotten, audit logs, bias/EEOC explainability (our provenance helps).
- **Ops:** observability (conflict rate, confidence distribution, source freshness),
  dead-letter queue for failed records, CI/CD, containerization.
- **Learning:** confidence weights calibrated from recruiter corrections; a real skill
  ontology/embeddings instead of the alias map.

The architecture is built for this: the engine is pure, the store is behind a
repository interface, and corrections already feed back — so each item above is an
extension, not a rewrite.

## Determinism with a live GitHub call

The GitHub adapter performs a real public-API GET (with a short timeout and graceful
degradation on any error). To keep the suite deterministic, tests patch the single
HTTP seam (`github_source._http_get_json`) with a fixture, and the committed `out/`
files / the gold test are generated with `--no-github`. Only the live UI/CLI demo
touches the network.

## Tests

```bash
pytest -q
```

54 tests: normalizers (incl. garbage→None), clustering + conflict resolution,
path resolver, all three `on_missing` policies, schema-validation failure,
mocked-GitHub enrichment, an end-to-end **gold** comparison, the trust layer
(explain trace, quality flags, review gating), incremental identity resolution +
store, the API, **résumé PDF/DOCX parsing**, the **grounded LLM extractor**
(hallucination-drop verification, no network), **anomaly detection**, and
**self-calibrating trust**.

## Résumé parsing — honest scope

PDF/DOCX résumés are a supported source (pdfplumber / python-docx + heuristics),
validated against a real résumé:

- **Contact + links** (email, phone, GitHub, LinkedIn, portfolio) — robust, and
  links are also read from **embedded hyperlink annotations** (résumés often show
  "LinkedIn"/"GitHub" as clickable text with the URL hidden from the visible text).
- **Skills are open-vocabulary** — everything listed in a *Skills / Technical Skills*
  section is extracted, known or not (PyTorch, FastAPI, LangChain, Neo4j…), then
  known ones are canonicalized and unknown ones kept verbatim. Skills are **not**
  limited to the alias map — the map only *canonicalizes*, it never gates.
- **Experience / education** — section- and layout-aware: handles the strict
  "Title at Company (dates)" form *and* the common real-résumé "Title | Company |
  Dec 2025 – May 2026" pipe form, with ALL-CAPS headings and unicode dashes handled.

It stays **conservative**: anything it can't parse confidently is skipped, never
invented. Exotic/graphical layouts and skills named only in prose are best-effort.

### Optional: grounded LLM extractor (LangChain + Groq)

For what the heuristics can't reach (prose skills, messy experience/education), an
optional LLM extractor ([transformer/extract/](transformer/extract/)) kicks in — and
it's built so it **cannot hallucinate**:

1. **Prompt** — strictly extractive: copy verbatim, null when absent, never infer.
2. **Structured output** — forced into a typed Pydantic schema at temperature 0.
3. **Grounding verification** — every returned string is checked against the source
   text; anything that doesn't literally appear is **discarded**. The model can only
   surface what the résumé actually says.

It's tagged `method=llm` and merged with the heuristic record by the normal engine
(so both corroborate, and provenance shows it). It activates **only** when
`GROQ_API_KEY` is set; otherwise the pipeline is heuristic-only and fully
deterministic. Any failure (no key, offline, rate-limit) falls back silently.

```bash
cp .env.example .env      # then add your Groq key
# GROQ_API_KEY=gsk_...
python app.py             # résumés now get the extra llm-tagged extraction
```

## Scope deliberately left out

LinkedIn (no public API / ToS); ML/LLM-based identity resolution and résumé
extraction (we use deterministic heuristics + a fuzzy-matched alias map). These are
conscious trade-offs, not oversights.
