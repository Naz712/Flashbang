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
- Deps in requirements.txt: anthropic, openai, python-dotenv, pypdf, streamlit
- Needs `.env` with ANTHROPIC_API_KEY and OPENAI_API_KEY (embeddings).

### Gaps vs new spec
1. No Course/Pdf/Topic entities — cards tagged with strings, not IDs.
2. No page-range tracking; concepts aren't tied to PDF pages.
3. No time estimation (hours per PDF, minutes per topic).
4. No completion percentage.
5. No decay/mastery model — SM-2 schedules cards but nothing at topic level
   decays or feeds a completion %.
