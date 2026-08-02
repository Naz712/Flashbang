# Flashbang — Launchpad AI Challenge write-up

*Draft. Word count (pillar sections): ~940. Numbers in this document are
measurements from the app's own spend tracker and test logs, not estimates —
where something is an estimate, it says so.*

## 1. Problem

Students own a broken study loop. The evidence-backed practices — retrieval
practice over re-reading, spaced repetition, pre-reading scaffolds, calibrated
self-testing — exist in separate tools that don't share data: Anki schedules
but you type every card; NotebookLM generates but nothing comes back at the
right time; lecture PDFs, tutorial sheets and flashcards never meet. The
practical failure is concrete: you re-read notes (feels productive, isn't),
go into new topics cold, and discover at the exam which topics were weak.

Success criteria, set before building: (1) one loop from PDF to scheduled
retrieval with no manual transcription; (2) every derived number traceable to
a measurement — an app that lies about your readiness is worse than no app;
(3) total running cost under $1/week for a five-module load, on the student's
own API key.

## 2. Approach

The defining decision was **removing the agents**. The first build ran four
LangGraph agents and a router. Measurement showed they added cost and latency
at the interaction layer and no value: reviewing is dealing due cards, which
is a `SELECT`; ingesting is a pipeline; card generation is a button. The
rebuilt system is de-agented — the server deals, buttons act, and exactly one
model call happens per graded answer (fast tier, structured teaching
feedback). One scoped assistant remains, in a corner bubble, for library
edits and search. Sessions became roughly two orders of magnitude cheaper.

Model calls are reserved for where formats genuinely vary (segmenting
arbitrary lecture decks; splitting tutorial sheets whose numbering schemes
differ per module); everything else is deterministic (report parsing, answer
retrieval by page, search over local embeddings — $0). Tutorial questions are
tagged with the student's own topic **ids** echoed from a supplied list,
never free text, because free-text tags can't join back to the notes.

Alternatives ruled out, with reasons: **pymupdf4llm** for extraction
(benchmarks favour it; on our actual slide decks it dropped equations
outright — tested, rejected, uninstalled). **AI-drawn diagrams** for topic
primers (built, measured at $0.0004–0.0117, judged not good enough to teach —
removed; the primer's analogy stayed text). **Raster image generation**
(cannot render correct labels; ~130× the cost of the primer it would
decorate). **Scheduling tutorial questions like cards** (long-form grading
cost; a filterable practice pool matched the actual need).

## 3. Evidence

All figures below are from the in-app spend tracker (per-call token logs ×
list prices) and timed runs on real course material.

- **Grading a typed answer:** $0.0003, 2.5–3.6 s, with structured feedback
  (what you had / the gap / model answer / memory hook) and an FSRS
  reschedule.
- **Ingesting a real 242-page lecture deck:** $0.17, ~4 min → 41 topics with
  contiguous page ranges. A boilerplate stripper removed 37% of extracted
  text (a nav strip repeated on all 242 pages) — measured before/after:
  179,687 → 111,757 chars.
- **Splitting a real tutorial sheet:** ~$0.05, 6–29 s. Six sheets → 79 leaf
  questions (3(a)/3(b) separate), 74 auto-tagged to note topics; inline
  solutions detected and excluded from question text, answer pages located
  for all 79.
- **Pre-reading primer:** $0.0003, 4–13 s, cached thereafter.
- **Total to load three courses (18 documents, 6 tutorials, primers,
  everything):** $0.75.
- **Baseline:** the pre-rebuild agent loop cost ~100× more per review
  session — the comparison that drove the de-agenting.
- **Correctness:** 12 offline test suites (scheduling maths, decay,
  parsers, sanitisation, cascade behaviour) run before every commit.

## 4. Constraints

Cost is a first-class feature: every model call logs purpose/model/tokens/
cost, and Analytics has a SPEND band showing all-time, 7-day, and unit costs
(per graded answer, per card generated). Projected load: ~$0.05 per study
day; **under $1/week for five modules** (~$10–15/semester) versus $60–120/yr
for the nearest subscription tool. Latency: every interactive action is
under ~4 s; the token-heavy quizzing can be exported to NotebookLM (a
generated examiner prompt; its graded report parses back in locally for $0).
Reliability: extraction falls back to vision for sparse pages; equations that
mangle in text extraction fall back to the rendered page itself; a moved
install directory cannot strand the database or files (both anchored, with
filename fallback). Honesty gates: metrics that lack data say so — the
per-card pace label reads "(assumed — needs 6 timed answers)" until the
median is real, and a course whose cards were never reviewed shows an em
dash, not 0%.

## 5. Honesty & Trajectory

Where it breaks today: (1) equation *text* is mangled by extraction — the
model reads around it and the page image is the fallback, but topic titles
containing maths can be ugly; (2) topic tagging has vocabulary gaps
(questions saying "tokens" missed a topic titled "Encoding" — 5 of 79 needed
a hand pass); (3) the personal baselines are gated on data that doesn't exist
yet (4 of 6 timed answers logged); (4) single-user, desktop-only, no sync —
by design, but a real limit.

Next: two real review sessions to unlock the measured baselines; deploy the
current build to a personal server (Zo) with a calendar automation writing
study blocks from `/api/plan.json`; trial a sponsored free-model endpoint
(the provider hook exists, untested); then a semester of dogfooding across
five modules — the only evaluation that counts.

---

## Appendix A — submission checklist

- [ ] Repo: `github.com/Naz712/Flashbang` is **private** — either flip to
      public or grant judge access before submitting.
- [ ] Demo video ≤3 min — script in `docs/DEMO_SCRIPT.md`, needs recording.
- [ ] This write-up: trim/adjust voice, paste into the submission form.
- [ ] Profile: intro + message to judges + resume.
