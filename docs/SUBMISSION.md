# Flashbang — Launchpad AI Challenge write-up

*Final. Every number below is a measurement from the app's own spend tracker,
test logs, or timed runs on real course material, re-read on 2026-08-03 —
where something is an estimate, it says so. Appendix B maps each claim to
where a judge can check it.*

## 1. Problem

The evidence-backed study practices — retrieval practice over re-reading,
spaced repetition, pre-reading scaffolds, calibrated self-testing — live in
separate tools that don't share data:

- Anki schedules, but you type every card.
- NotebookLM generates, but nothing comes back at the right time.
- Lecture PDFs, tutorial sheets and flashcards never meet.

The practical failure: you re-read notes (feels productive, isn't), go into
new topics cold, and discover at the exam which topics were weak.

Success criteria, set before building:

1. One loop from PDF to scheduled retrieval, no manual transcription.
2. Every derived number traceable to a measurement — an app that lies about
   your readiness is worse than no app.
3. Under $1/week running cost for a five-module load, on my own API key.

## 2. Approach

**The defining decision was removing the agents.** The first build ran four
LangGraph agents and a router. Measurement showed they added cost and latency
at the interaction layer and no value: reviewing is dealing due cards — a
`SELECT`; ingesting is a pipeline; card generation is a button. In the
rebuild the server deals, buttons act, and exactly one model call happens per
graded answer (fast tier, structured teaching feedback). One scoped assistant
remains, in a corner bubble, for library edits and search.

**Model calls only where formats genuinely vary:** segmenting arbitrary
lecture decks; splitting tutorial sheets whose numbering differs per module.
Everything else is deterministic and $0 — report parsing, answer retrieval by
page, search over local embeddings. Tutorial questions are tagged with my own
topic **ids** echoed from a supplied list, never free text, because free-text
tags can't join back to the notes.

**Alternatives ruled out, with reasons:**

- **pymupdf4llm** extraction — benchmarks favour it; on my slide decks it
  dropped equations. Tested, rejected, uninstalled.
- **AI-drawn primer diagrams** — built, measured at $0.0004–0.0117, not good
  enough to teach. Removed; the primer's analogy stayed text.
- **Raster image generation** — cannot render correct labels; ~130× the cost
  of the primer it would decorate.
- **Scheduling tutorial questions like cards** — long-form grading cost; a
  filterable practice pool matched the actual need.

## 3. Evidence

All figures are from the in-app spend tracker (per-call token logs × list
prices) and timed runs on real course material.

- **Grading a typed answer:** $0.00022 (tracker unit cost), 2.5–3.6 s —
  structured feedback (what you had / the gap / model answer / memory hook)
  plus an FSRS reschedule.
- **Review pace is measured, not assumed.** The app refused to show a
  per-card pace until six timed answers existed — the label read
  "(assumed)". After real sessions on 2–3 Aug it flipped to the measured
  median: **53 s/card** against the 84 s I had assumed. The gate did its
  job: my assumption was 58% high.
- **Ingesting a 242-page lecture deck:** $0.17, ~4 min → 41 topics with
  contiguous page ranges. The boilerplate stripper removed 37% of extracted
  text (a nav strip on all 242 pages): 179,687 → 111,757 chars, measured
  before/after.
- **Splitting six tutorial sheets:** $0.32 total (~$0.05/sheet), 6–29 s
  each → 79 leaf questions (3(a)/3(b) separate), 74 auto-tagged; inline
  solutions excluded; answer pages located for all 79.
- **Pre-reading primer:** $0.0003, 4–13 s, cached thereafter.
- **Total, all-time, everything** (3 courses, 19 documents, 6 tutorials, 42
  logged calls): **$0.75**.
- **Baseline:** the pre-rebuild agent loop cost ~100× more per review
  session — the comparison that drove the de-agenting.
- **Correctness:** 12 offline suites (scheduling maths, decay, parsers,
  sanitisation, cascades), all passing as of this write-up, plus one live
  ingestion suite; 92 commits, each message stating what it proves.

## 4. Constraints

- **Cost is a first-class feature.** Every model call logs
  purpose/model/tokens/cost; Analytics shows all-time, 7-day, and unit
  costs. Projected load ~$0.05 per study day — **under $1/week for five
  modules** (~$10–15/semester) versus $60–120/yr for the nearest
  subscription tool.
- **Latency.** Every interactive action is under ~4 s. Token-heavy quizzing
  exports to NotebookLM via a generated examiner prompt with embedded
  question ids; its graded report parses back in locally for $0. External
  evidence decays like a first recall and can only raise a displayed
  score — never the FSRS schedule or exam projection.
- **Reliability.** Extraction falls back to vision for sparse pages; mangled
  equations fall back to the rendered page itself; a moved install directory
  cannot strand the database or files.
- **Honesty gates.** Metrics that lack data say so: a course whose cards
  were never reviewed shows an em dash, not 0%, and every derived number
  carries its evidence line.

## 5. Honesty & Trajectory

**Where it breaks today:**

1. Equation *text* mangles in extraction — the model reads around it and the
   page image is the fallback, but topic titles with maths can be ugly.
2. Topic tagging has vocabulary gaps — questions saying "tokens" missed a
   topic titled "Encoding"; 5 of 79 needed a hand pass.
3. Confidence calibration is still gated — only 2 confidence-tagged answers
   exist, so those bands stay empty.
4. Single-user, no sync — by design, but a real limit.

**Since the draft:** the review-pace baseline went from assumed to measured
(above); the app now runs on my own Zo Computer machine as a supervised,
login-gated service, so the loop survives my laptop being off; the
NotebookLM tutor prompt was rebuilt around grounded citations.

**Next:** a calendar automation writing study blocks from the read-only
`/api/plan.json` feed, a Telegram nudge, and an off-machine database
backup — each ends in an OAuth consent only I can click; a trial of a
sponsored free-model endpoint (the hook exists, untested); then a semester
of dogfooding across five modules — the only evaluation that counts.

---

## Appendix A — submission checklist

- [ ] Repo: `github.com/Naz712/Flashbang` is **private** — either flip to
      public or grant judge access before submitting.
- [ ] Demo video ≤3 min — script in `docs/DEMO_SCRIPT.md`, needs recording.
- [ ] This write-up: paste into the submission form.
- [ ] Profile: intro + message to judges + resume.

## Appendix B — where each claim can be checked

| Claim | Evidence in the repo/app |
|---|---|
| $0.75 all-time; unit costs | Analytics → SPEND tab; `api_spend` rows (42 calls, per-purpose breakdown) |
| 53 s/card measured (84 s assumed before) | `/api/state` → `budget.sec_per_card`; timed rows in the answer log |
| 242-page deck → 41 topics, $0.17 | spend rows purpose=`segmentation`; RB2302 course page |
| 37% boilerplate stripped (179,687 → 111,757 chars) | commit `d698a5c` and its logged before/after |
| 6 sheets → 79 questions, 74 auto-tagged | spend rows purpose=`tutorial split`; Tutorials screen; commit `7730612` |
| 12 offline suites pass | `tests/check_*.py` run logs in `TESTING.md`; run them — no API key needed |
| ~100× de-agenting saving | frozen original build (branch `master`) with its own spend logs, side-by-side |
| External reviews never touch scheduling | `check_external.py`; commit `1243762` |
