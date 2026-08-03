# Flashbang

A de-agented study app: one honest loop from lecture PDF to scheduled
retrieval, on the student's own API key. Built for the Launchpad AI
Challenge. The full write-up is in [docs/SUBMISSION.md](docs/SUBMISSION.md).

## What it does

- **Ingest** — drop lecture PDFs; a model call segments each deck into
  editable topics with page ranges and time estimates. Repeated boilerplate
  is stripped before any model sees the text (37% of one real 242-page deck).
- **Read** — a continuous-scroll reader with a cached pre-reading primer
  (gist, one analogy with its limits), notes, and blackout boxes that snap
  to the words under your drag.
- **Review** — the server deals due cards within your daily time budget;
  you type answers; exactly one fast-tier model call grades each one
  ($0.00022) with teaching feedback, and FSRS reschedules.
- **Tutorials** — problem sheets are split into leaf questions and tagged
  against your own topic ids; worked solutions are retrieved by page, never
  rewritten.
- **NotebookLM round-trip** — export an examiner prompt, quiz yourself
  there, paste the graded reply back. It parses locally for $0 and can only
  raise a displayed score, never the schedule.
- **Analytics** — six tabs with honesty gates: metrics that lack data say
  so, and a SPEND band shows exactly what the app has cost ($0.75 total to
  load three real courses).

The design premise: Claude and NotebookLM are better tutors than anything
worth rebuilding, so the app supports them instead of replacing them. It
owns what they cannot: the schedule and the evidence.

## Run it

```
python -m venv flashbang
flashbang\Scripts\pip install -r requirements.txt
```

Create `.env` in the project root with `OPENAI_API_KEY=...` (or
`ANTHROPIC_API_KEY=...`; any OpenAI-compatible endpoint works via
`OPENAI_BASE_URL` + `OPENAI_MAIN_MODEL`/`OPENAI_FAST_MODEL`). Then:

```
flashbang\Scripts\python server.py
```

Open http://localhost:5002.

## Tests

Twelve offline suites need no API key:

```
flashbang\Scripts\python tests\check_db.py
```

...and likewise for the other `tests\check_*.py` files. `check_ingest.py`
is the one live suite (real PDF + API key). Test history and the SM-2
versus FSRS A/B battery live in [TESTING.md](TESTING.md).

## Repo map

| Path | What |
|---|---|
| `server.py` | Flask app: review dealing, ingest, tutorials, analytics APIs |
| `llm_utils.py` | provider layer, spend tracking, transient-failure retries |
| `pdf_ingest.py` | extraction, boilerplate stripping, segmentation, vision fallback |
| `static/app.js` + `templates/index.html` | the whole UI |
| `tests/` | 12 offline suites + 1 live |
| `docs/SUBMISSION.md` | the five-pillar challenge write-up |
| `docs/DEMO_SCRIPT.md` | 3-minute demo shot list |
| branch `master` | the original agent-based build, frozen for the A/B comparison |

All model spend is logged in-app; every number claimed in the write-up is
traceable to a spend-tracker row, a test, or a commit.
