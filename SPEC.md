# Flashbang — Improved Organazer Flashcard Study App

## Vision
An agent-powered study app: you feed in notes/PDFs, the agent breaks them into
topics, estimates study time, tracks completion, and decays your knowledge
score if you don't revise — with flashcards tied to every level.

## Core Features

### 1. Ingestion & Topic Splitting
- Upload notes (PDF or text) under a course.
- The agent reads the pages and splits them into **actual content topics**
  (not just by page number — by what the content is about).
- Each topic records which page range(s) of the PDF it covers.

### 2. Time Estimation
- Agent estimates **total hours** to cover the whole document.
- Agent estimates **time per topic** (based on density, difficulty, length).

### 3. Completion Tracking
- **Percentage of completion per PDF**, driven by which topics are done.
- Topic-level status: not started / in progress / covered.

### 4. Decay (Spaced-Repetition Pressure)
- If a topic isn't revised within a certain window, its mastery **decays**.
- Decay pulls the completion percentage back down — the PDF is only "done"
  while knowledge is fresh.
- (Decay curve, window length, and floor: TBD — likely Ebbinghaus-style
  exponential, reset on each review.)

### 5. Flashcards
- Every flashcard carries three foreign keys:
  - `pdf_id`   → the source document
  - `course_id` → the course it belongs to
  - `topic_id` → the specific topic within the PDF
- Reviewing a topic's flashcards counts as revising that topic (feeds decay reset).

## Data Model (draft)

```
Course   { id, name }
Pdf      { id, course_id, filename, total_pages, est_total_hours, uploaded_at }
Topic    { id, pdf_id, course_id, title, page_start, page_end,
           est_minutes, status, mastery, last_reviewed_at }
Flashcard{ id, topic_id, pdf_id, course_id, front, back,
           last_reviewed_at, ease/interval fields }
```

## Open Questions (to resolve as existing Organazer files come in)
- [ ] What stack is the existing Organazer built on? (framework, storage)
- [ ] What's worth keeping vs rebuilding?
- [ ] Decay parameters: how long until decay starts, how fast, what floor?
- [ ] Does reviewing flashcards fully restore mastery, or partially?
- [ ] How does the agent get called — API key in the app, or Claude Code driving it?

## Assessment Log (existing Organazer files)

### Batch 1 — 2026-07-15
Stack: Python + SQLite + Anthropic API, terminal REPL + (referenced) Streamlit dashboard.

| File | Verdict | Notes |
|---|---|---|
| agent.py | KEEP | Thin terminal REPL over agent_core.run_turn. Fine as-is. |
| agent_core.py | KEEP, extend | Clean tool-use loop shared by terminal + Streamlit. New tools slot into handle_tool + system prompt. |
| database.py | REWORK schema | Has events/notes/cards/insights. Missing courses, pdfs, topics tables. Cards use free-text subject/topic instead of FKs. FKs not enforced (no PRAGMA foreign_keys=ON); deletes can leave dangling refs. Dates stored day-granular — decay wants full timestamps. |
| sm2.py | KEEP | Textbook SM-2, correct. Decay layer builds on top of it, doesn't replace it. |
| grading.py | KEEP, harden | Haiku-graded answers, good design. json.loads on raw output has no retry/fallback — brittle. |
| tools.py | KEEP, extend | 20 tool schemas, well written. Doc drift: generate_cards_for_session says "3 cards each, cap 15" but code defaults are 5/80. |

### Batch 2 — 2026-07-15

| File | Verdict | Notes |
|---|---|---|
| pdf_ingest.py | REWORK | Vision extraction of the WHOLE PDF in one Claude call. No page numbers in output; max_tokens=8000 silently truncates long PDFs. Topic splitting needs per-page (or per-chunk) extraction with page provenance. |
| pdf_reader_test.py | KEEP idea | pypdf local extraction — free, fast, and naturally per-page. Good first-pass path; fall back to vision for scanned/diagram-heavy pages. |
| generation.py | KEEP, harden | extract_concepts + generate_cards, thoughtful prompts (one-fact-per-card rule). Brittle json.loads, max_tokens=2000 too low for big card batches, single subject/topic per extraction call. |
| embeddings.py | KEEP | OpenAI text-embedding-3-small. Means the app needs BOTH an Anthropic and an OpenAI key. |
| backfill_embedding.py | KEEP | One-off utility, fine. |

Still missing: search.py, app.py (Streamlit), .env, calendar.db.

### Environment
- venv: `flashbang/` (Python 3.13.7). Activate: `.\flashbang\Scripts\activate`
- Deps in requirements.txt: anthropic, openai, python-dotenv, pypdf, streamlit, numpy
- Needs `.env` with ANTHROPIC_API_KEY and OPENAI_API_KEY (embeddings).

## Architecture (v2 — implemented 2026-07-16)

**Run it:** `streamlit run app.py` (chat + dashboard) or `python agent.py` (terminal).

- `orchestrator.py` — one conversation, routes each message to a specialist;
  session pinning rides on the study-session tools.
- `router.py` — pin fast-path → keyword heuristics → Haiku classifier.
- `agents.py` — 4 specialists (ingestion / review / organizer / planner),
  each a system prompt + tool subset.
- `agent_core.py` — generic run_turn loop + TOOL_HANDLERS registry.
- `tools.py` — TOOL_SCHEMAS dict; tools_for(names) builds per-agent subsets.
- `database.py` — flashbang.db: courses → pdfs → pdf_pages → topics →
  notes/cards → insights, plus study_sessions/session_topics (auto study log).
  FKs enforced, full ISO timestamps, card FKs derived server-side from topic.
- `pdf_ingest.py` — per-page pypdf extraction, Claude-vision fallback for
  sparse pages (batched sub-PDFs, no silent truncation), topic segmentation
  with page ranges + per-topic minute estimates (chunked for long PDFs).
- `mastery.py` — Ebbinghaus decay: R = exp(-t/S), S ≈ 3.476 × SM-2 interval
  (card at its due date = 75% retention; never-reviewed = 0). Topic mastery =
  mean retention; PDF completion % = est_minutes-weighted topic mastery.
  Computed at read time, nothing stored.
- `generation.py` / `grading.py` — per-topic concept extraction and card
  generation; Haiku answer grading with JSON prefill.
- `llm_utils.py` — shared client + robust JSON parsing (retry once, refuse
  truncated output).
- `tests/` — check_db, check_mastery, check_search, check_router (offline),
  check_ingest (needs API key + a real PDF).

Old calendar CRUD is gone: the calendar is now the auto-written study log.

### Blackout tool (2026-07-26, frameworks branch)

Image occlusion in the topic page viewer: drag black boxes over key facts in
blackout mode; boxes persist (`occlusions` table, coords normalized 0-1 to
the page box) and render hidden on every reopen — recall, then click to
peek. Reveal-all toggle; blackout-mode click deletes. Works on both the
pdf.js canvas path and the extracted-text fallback (boxes overlay the page
container, not the canvas).

Decisions:
- **Boxes are visual only, not cards.** A box never touches SM-2/FSRS or
  mastery — occlusion recall is self-checked, unscheduled study. (Rejected:
  auto-creating a card per box — grading a visual recall needs image cards
  the review flow doesn't have, and silent card creation would pollute the
  deck.)
- **Normalized coords over pixels** so any render width, DPR, or future
  page-at-a-time layout shows boxes correctly. (Rejected: pixel coords tied
  to one canvas size.)
- **Cascade with the pdf** (`ON DELETE CASCADE`) so deleting a document
  can't orphan boxes or block the manual-delete button.

### De-agented architecture + IA v3 (2026-07-29, frameworks branch)

**The app is no longer chat-first.** The four-agent router/orchestrator was
removed from the runtime after the gap-report change made it redundant: the
only per-interaction model call left is the fast-tier grader.

- **Review** — the SERVER deals cards (`/api/review/start|answer|skip|undo|
  end`): due cards most-overdue-first, capped by the daily minute budget;
  the user types an answer; one grading call returns structured feedback;
  FSRS reschedules; failures are re-asked unscored at the end; ending
  emits a session summary plus the gap report. ~100× cheaper per session
  than the agent loop, which re-sent the whole history to gpt-4o per turn.
- **Ingestion** is a button (`/api/ingest_auto`): upload → read → segment →
  save, with the topic-split editor as the correction tool afterwards.
  **Card generation** is a per-topic button.
- **Assistant** — a corner bubble opens ONE scoped agent (library edits,
  notes search, stats, planning). It refuses review/ingest/card-gen and
  points at those buttons. Runs only when opened; history capped.
- **Screens: Home | Review | Analytics | Cards.** Home is a course canvas;
  a course opens to documents/topics on the left and that course's metrics
  (completion, due, time invested, reading, exam readiness) on the right —
  the single navigator. The Reading tab was folded into it. Analytics is
  ordered by the learning-analytics evidence: where-you-stand → pacing →
  trends → diagnostics → reading.
- **Removed:** slash commands, command palette, the floating focus timer,
  the right rail, the personal-forgetting-curve/time-of-day/Brier panels.
  Study blocks are logged by the reader's sidebar timer and by review
  sessions themselves.

Decisions:
- **Agency was removed where it added no value, not on principle.** The A/B
  eval showed the agent loop bought nothing at the interaction layer while
  costing latency and tokens; the same modules still power the assistant
  bubble, where being able to say what you want *does* beat a button.
- **Grading stays an LLM job** — it's judgement, not routing.

### Reading hub (2026-07-27, frameworks branch)

A separate top-level space for reading: page-at-a-time reader (the topic
viewer, now with ‹ ›/arrow-key nav), window-box annotations (outlined box +
comment in the side panel, `annotations` table), and reading blocks — the
sidebar countdown logs `study_sessions.kind='reading'` attributed to the
open document.

Decisions:
- **Reading time is logged in the same table, separated by kind** rather
  than a second sessions table — one migration (CHECK rebuild) instead of
  duplicated session tooling, and each hub filters by kind. (Rejected: a
  `reading_sessions` table — would fork streak/heatmap/time logic.)
- **Flashcard analytics exclude reading** (`FLASHCARD_KINDS` filter):
  Progress answers "is retrieval working", the Reading hub answers "am I
  putting in reading time". Mastery still only ever moves through reviews.
- **Annotations are their own table, not occlusions-with-text** — the two
  overlays have different lifecycles (notes are read-mostly reference,
  blackouts are self-testing) and different UI affordances.

### Gaps vs new spec
1. No Course/Pdf/Topic entities — cards tagged with strings, not IDs.
2. No page-range tracking; concepts aren't tied to PDF pages.
3. No time estimation (hours per PDF, minutes per topic).
4. No completion percentage.
5. No decay/mastery model — SM-2 schedules cards but nothing at topic level
   decays or feeds a completion %.
