# Demo Guide — Multi-Source Candidate Data Transformer

Everything you need to run, present, and defend the project: a tight **2-minute
script**, an **extended walkthrough**, a full **end-to-end architecture
explanation**, the **design decisions** to defend, and **interviewer Q&A**.

---

## 0. Before you record (setup)

```powershell
pip install -r requirements.txt          # one time
python -m pytest -q                       # sanity: 61 passing

# clean slate for a repeatable demo (the store re-seeds samples on next start)
Remove-Item candidates.db -ErrorAction SilentlyContinue

# OPTIONAL: enable the grounded LLM extractor for the live résumé
Copy-Item .env.example .env               # then edit .env -> GROQ_API_KEY=gsk_...
```

Have ready: your **résumé PDF** and your **GitHub handle** (`1ms23ai009-lgtm`).

The seeded sample data already contains three instructive candidates:
- **Jane Doe** — the same person across CSV + ATS + notes with a **name conflict**.
- **Carlos Reyes** — an ATS typo (**graduation year 2031**) → **anomaly** flag.
- **Sam Lee** — only a name + a garbage phone → **sparse / no-email** → review.

---

## 1. The 2-minute script (timed)

> Run `python app.py` → open `http://127.0.0.1:5000`. Keep a terminal handy.

| Time | On screen | Say (roughly) |
|------|-----------|---------------|
| 0:00–0:15 | The `samples/` folder, then the console dashboard | "Candidate data arrives from many places at once — a recruiter CSV, an ATS export with different field names, résumés, GitHub. My transformer fuses them into **one trustworthy profile per candidate**, with provenance and confidence. The rule is: **wrong-but-confident is worse than honestly-empty** — it never invents." |
| 0:15–0:55 | **"Add a candidate"** panel → upload your résumé, type GitHub `1ms23ai009-lgtm`, Ingest → land on your profile | "This is the real recruiter workflow. From my résumé it pulled skills, experience, education — even my LinkedIn and GitHub from the **embedded hyperlinks**. From the **live GitHub API** it added my repo languages. Every field shows **where it came from** and a **confidence**. And notice `full_name` is my real name from the résumé, not my GitHub nickname — because trust is **per-field**: GitHub is great for skills, not for a legal name." |
| 0:55–1:30 | Click **Jane Doe** → the highlighted `full_name` conflict → **Override** → back to dashboard → **calibration panel** | "Here two sources disagreed on the name. It picked the higher-trust source, **penalized confidence**, and kept the loser in the trace — nothing hidden. I override it… and back on the dashboard the **trust weight for that source dropped**. The system *learns*: a source that gets corrected loses trust." |
| 1:30–1:50 | Terminal: run the custom-config CLI | "Same engine, no code change — a runtime **config reshapes the output** and it's **schema-validated**. With the LLM off it's **byte-deterministic**, which is why my committed outputs and gold test are reproducible." |
| 1:50–2:00 | Back to a profile | "The design decision I'm proudest of: a **hard separation between the canonical record and the projection layer** — the engine never changes, the config only reshapes the view." |

Custom-config command for the 1:30 beat:
```powershell
python -m transformer --inputs samples --config samples/configs/custom.json --no-github --out out/custom_output.json
```

**Rubric hit:** default output ✓ (profiles), custom-config output ✓ (CLI), one design
decision ✓ (projection separation), one edge case ✓ (conflict / anomaly / degradation).

---

## 2. Extended walkthrough (~5 min, optional deeper cut)

1. **Ingest yourself** (as above) — point out provenance, confidence colors, per-field
   sources, hyperlink-extracted links, live GitHub languages, and (if `.env` set) the
   grounded **LLM** filling prose gaps.
2. **Carlos → anomaly.** Open Carlos: the trust panel flags **"future graduation year
   2031"** and routes him to review. "It doesn't silently trust a data-entry typo."
3. **Sam → sparse.** Open Sam: **no email, low completeness** → flagged with explicit
   reasons. Honest-empty, not invented.
4. **Custom + strict configs** in the terminal:
   ```powershell
   python -m transformer --inputs samples --config samples/configs/custom.json --no-github
   python -m transformer --inputs samples --config samples/configs/strict.json  --no-github
   ```
   Strict uses `on_missing: "error"` and `required` — Sam Lee raises a **structured,
   isolated error** while the rest of the batch still completes.
5. **Trust report** (the whole trust layer as JSON):
   ```powershell
   python -m transformer --inputs samples --no-github --report out/trust_report.json
   ```
6. **The API** (event-driven shape):
   ```powershell
   python service.py    # port 5001
   # GET /candidates, POST /ingest, POST /candidates/<id>/override, GET /calibration
   ```
7. **Delete** your test candidate from the profile page to reset.

---

## 3. End-to-end: how the system actually works

### The pipeline

```
inputs ─► detect/route ─► source adapters ─► normalize ─► merge & resolve ─► confidence
                                                                                  │
                                                CANONICAL RECORD (internal, full schema)
                                                                                  │
                                          projection (runtime config) ─► validate ─► output
```

The **central design idea**: a hard separation between the **internal canonical
record** and the **output projection**. The engine always builds the full canonical
record; a runtime config only reshapes a *view* of it — same engine, no code changes.

### Stage by stage

- **Detect / route** (`pipeline.py`) — each file/URL goes to the right adapter by type.
- **Source adapters** (`transformer/sources/`) — one per source; they *read and tag*,
  never normalize or merge. Each emits `SourceRecord`s keyed by **canonical** field
  names (the ATS adapter has an explicit field-mapping table since its keys differ).
  Sources: **CSV, ATS JSON** (structured); **GitHub live API, résumé PDF/DOCX,
  recruiter notes** (unstructured).
- **Normalizers** (`transformer/normalize/`) — pure, **total** functions: garbage →
  `None`, never an exception. Phones → **E.164** (`phonenumbers`); dates → **`YYYY-MM`**
  (or `YYYY`; never invent a month); country → **ISO-3166 alpha-2** (deterministic
  alias table + `pycountry`); skills → **canonical** (alias map + fuzzy, but
  **open-vocabulary** from a résumé's Skills section so unknown skills survive).
- **Merge & resolve** (`merge/resolver.py`) — cluster records into one candidate
  (shared email / phone / GitHub / name), then per field pick a **reliability-weighted
  winner**. **Trust is per-field**: e.g. a GitHub display name is a nickname, so GitHub
  is down-weighted for `full_name` but not for skills. Every losing value is retained
  in the trace. Lists are unioned + deduped; skills ranked by corroboration.
- **Confidence** (`merge/confidence.py`) — deterministic: `source_weight ×
  method_certainty`, +bonus when sources agree, ×penalty on conflict, clamped to
  [0,1]. No randomness, no time, no network → identical inputs, identical numbers.
- **Projection + validation** (`transformer/projection/`) — apply the runtime config
  (select fields, remap via `from`, per-field normalize, toggle confidence/provenance,
  `on_missing` = null/omit/error), then validate the view against a JSON Schema derived
  from the config. The default schema validates the default output.

### The trust layer (`transformer/trust/`)

The engine says *what* the profile is; the trust layer says *how much to believe it*.
It reuses data the resolver already computed:
- **Explain trace** — per field: the chosen value, the alternatives it beat (with
  sources/weights), whether a conflict fired, and a plain-English reason.
- **Quality / conflict report** — completeness %, disagreeing fields with competing
  values, low-confidence fields, and **anomaly** flags (future dates, impossible years).
- **Review gating** — a confidence/completeness threshold routes shaky profiles to
  `needs_review` with explicit reasons, so a wrong-but-confident profile is flagged,
  never trusted silently.
- **Self-calibration** — each source's **override rate** feeds back: a source recruiters
  keep correcting loses trust. The system improves as it's used.

### The store + identity resolution (`transformer/store/`)

SQLite behind a repository interface (Postgres-portable schema). Ingesting a record
runs **incremental identity resolution**: extract **blocking keys** (email / phone /
GitHub / name), consider only candidates sharing a key (indexed — no O(n²)), score
them, then **re-resolve only that one candidate**. Recruiter **corrections persist** as
a highest-trust `recruiter_override` source and **win on re-resolve** — closing the
human-in-the-loop. Re-ingesting the same logical source (by `origin`) **refreshes** it
rather than duplicating.

### Résumé + grounded LLM extraction

Résumés: pdfplumber / python-docx for text, **plus embedded hyperlink annotations**
(résumés show "LinkedIn"/"GitHub" as clickable text). Skills are open-vocabulary;
experience/education parse common layouts. For prose the heuristics can't reach, an
**optional LLM extractor** (LangChain + Groq) runs — and **cannot hallucinate**:
strictly-extractive prompt + typed schema (temp 0) + a **grounding pass that drops any
value not literally in the source text**. It's `method=llm`, merged by the normal
engine, opt-in via `GROQ_API_KEY`, and degrades silently to the heuristics.

### Surfaces

- **Review console** (`app.py`, :5000) — the recruiter workflow: inbox, provenance,
  color-coded confidence, conflicts, override, delete, self-calibration, and the
  interactive **"Add a candidate"** ingest.
- **JSON API** (`service.py`, :5001) — event-driven: `/ingest`, `/candidates`,
  `/review-queue`, `/candidates/<id>/projection|override|review`, `/calibration`.
- **CLI** (`python -m transformer`) — scriptable; used for the gold test and outputs.

---

## 4. Design decisions you can defend

- **Canonical record ↔ projection layer separation** — the runtime "twist" without
  touching the engine; the projection is the *only* thing a config changes.
- **Never invent** — total normalizers, grounded LLM, review gating. `null` beats a guess.
- **Deterministic where the domain is closed** (country, phone, dates), **LLM only for
  open prose** — and always grounded. Country stays `pycountry`, not an LLM guess.
- **Per-field source trust** — a source can be authoritative for some fields and not
  others (GitHub name = nickname).
- **Confidence is a fixed, explainable function** — no black-box scoring; every field
  is traceable to a source and method.
- **Incremental, indexed identity resolution** — the real scale story, not a batch toy.

## 5. Edge cases handled

1. Conflicting scalars (name/company) → weighted winner, losers kept, confidence lowered.
2. Garbage input (`phone="N/A"`, `date="sometime 2021"`, invalid JSON) → dropped, no crash.
3. Skill aliasing (`reactjs`/`React.js` → `React`) + **open-vocab** unknown skills kept.
4. Missing required field under `on_missing:"error"` → isolated per-candidate error.
5. Open-ended dates (`present`) → `end = null`. Future/impossible dates → anomaly flag.
6. GitHub unreachable / handle invalid → empty enrichment, profile still built.
7. Re-ingesting the same résumé/GitHub → refreshed, not duplicated.

## 6. Likely interviewer questions → crisp answers

- **"Is it deterministic?"** Yes with the LLM off — the gold test asserts byte-stable
  output. The LLM is opt-in and non-deterministic by nature, so committed outputs use
  `--no-github` and heuristics only.
- **"How do you resolve conflicts?"** Reliability-weighted winner with per-field trust;
  all candidates kept in provenance; confidence penalized on disagreement.
- **"How does it scale?"** Store path does indexed blocking-key lookups and re-resolves
  only the affected candidate — never the whole dataset. Batch clustering is O(n).
- **"How do you stop the LLM hallucinating?"** Extractive prompt + typed schema +
  grounding verification that discards anything not in the source text. Proven by a test.
- **"Why not use the LLM for everything (e.g. country)?"** Closed domains are solved
  deterministically (correct, free, instant). The LLM adds non-determinism, cost, and
  hallucination risk where it isn't needed; I reserve it for open prose.
- **"What did you deliberately leave out?"** LinkedIn (no public API / ToS), ML-based
  identity resolution, and full arbitrary-résumé parsing (LLM is the path there).
- **"Production next steps?"** Postgres + a blocking/search index, Kafka ingestion,
  auth + PII/compliance, observability, and confidence weights learned from corrections.

## 7. Rubric coverage (quick map)

| Requirement | Where |
|---|---|
| Canonical profile, normalized, deduped, provenance + confidence | engine + `out/` |
| ≥1 structured + ≥1 unstructured source | CSV/ATS + GitHub/résumé/notes |
| Normalized formats (phone/date/country/skills) | `transformer/normalize/` |
| Runtime config (select/remap/normalize/toggle/on_missing) + validate | `projection/` |
| Deterministic & explainable · robust · scale | gold test · total normalizers · store |
| Minimal surface | review console + API + CLI |
| Tests / gold profile | 61 tests, `tests/gold/` |
| Demo video | this script |
