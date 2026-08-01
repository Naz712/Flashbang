# Flashbang — continuation brief

Paste this into a new chat to pick up where the last one left off.

## Where the code is

- **Primary: `C:\Users\Nazzoom\Desktop\Flashbang-frameworks`** (branch `frameworks`,
  port 5002). Run: `.\flashbang\Scripts\python.exe server.py`
- **Frozen reference: `C:\Users\Nazzoom\Desktop\Flashbang`** (branch `master`, port
  5001) — the original hand-rolled build, kept for the A/B story. Do not develop here.
- **Remote:** private repo `github.com/Naz712/Flashbang` (both branches pushed).
- **Deployed:** `https://flashbang-nazzoom.zo.computer` — a personal (Zo-login-gated)
  site. **Badly out of date** — predates the de-agenting, so its front end no longer
  matches its server. Updating means asking Zo's agent to swap the single hosted-service
  slot back to SSH, scp the changes, then swap back.

## What the app is now

A study app, **de-agented**. The four LangGraph agents and the router were removed from
the runtime after measurement showed they added cost and latency but no value at the
interaction layer. What remains:

- **Review** — the *server* deals due cards (`/api/review/start|answer|skip|undo|end`),
  most-overdue-first, capped by a daily minute budget. You type an answer; one
  fast-tier grading call returns structured teaching feedback; FSRS reschedules;
  failures are re-asked unscored at the end; ending emits a summary plus a **gap
  report** with source-page buttons and a one-click **AI-tailored tutor prompt** to
  paste into an external chat. ~100× cheaper per session than the old agent loop.
- **Ingestion** is a button (upload → vision-fallback extraction → segmentation →
  auto-save), with a **force-vision** checkbox for diagram-heavy decks. Card generation
  is a per-topic button.
- **Assistant** — a corner bubble running ONE scoped agent (library edits, notes search,
  stats, planning). It refuses review/ingest/card-gen and points at the buttons.
- **Screens:** Home (course canvas) → course page · Review · Analytics · Cards, plus a
  reader with blackout boxes and window-box annotations.
- **Spend tracker** — every model call logs purpose/model/tokens/estimated cost;
  Analytics has a SPEND band. Embeddings and search are local, so $0.

Architecture decisions and their rejected alternatives are in `SPEC.md`; every test run,
benchmark and bug is in `TESTING.md`.

## In flight: the design-system rewrite

The design system lives at `~/Downloads/flashbang Design System` (also a Claude Design
project, synced from this repo). `design_handoff_flashbang/README.md` specs all six
screens; its `tokens/` + `css/` are the source of the visual layer.

**The look:** Figma/Bauhaus primaries on white. Page `#F4F5F5`, cards white with **no
border and no shadow**, 12px radius, IBM Plex Sans/Mono. Cobalt `#1B4FD8` is the only
hue that may carry white text — it marks the single primary action per screen. Mastery
hues (red/yellow/green) are **fills only, never type**, so a bar never ships without its
percentage beside it. Nothing is rotated; there is no elevation layer.

**Phase 1 is done** (`ee025bb`, `d5d58e6`): token layer into `static/app.css` (old rules
kept below a `LEGACY` marker), the 208px nav shell, and Home's course tile — ink band
header, 44px mono numeral, six-week sparkline, mastery bar, week strip. Backed by a new
`course_snapshots` table, because a completion trend cannot be reconstructed after the
fact.

**Phase 2 is done** (`b264616`): the course page. The four numbers moved from a
right-hand column into one ink-bordered metrics band across the top, which gives the
documents the full 1160px and lets them sit two-up. Evidence line inside the band's
card, under a hairline. Documents are `fb-card` disclosures whose topics show a
`Make cards` button *instead of* a card count when they have none; the split editor and
the merged-PDF export carried over. Reading dropped below the documents. Each screen
that converts also deletes its legacy CSS block — that is the pattern to keep.

**Phase 3 is done** (`4915b3c`, `c076e0a`, `19a9648`), in three commits: the deck
state, the session surface, and the report. Notes worth keeping:

- The deck rail lost its course colour dot — colour means mastery here, nothing else.
- Today's budget sentence is derived from the deal, not written.
- The grade card marks only the evaluative pair (✓ *You had* / ✗ *The gap*); its
  next-review footer is one track with the old interval as a ghost tick. This needed a
  server fix: `/api/review/answer` was `str()`-ing `review_card()`'s dict into a meta
  string, so the footer would have printed a raw Python dict repr.
- The report is a third review state, not a chat message; it replaces the transcript.
  Recall there is retrieval-weighted across **marks** and ships beside `accuracy`
  (cards passed) with the arithmetic visible — do not collapse the two. The gap list
  is `quality <= 3` but scheduling extends at `quality >= 3`; conflating those two
  thresholds is what made the first build contradict itself.

**Phases left, in the handoff's order:**

1. **Analytics** — five tabbed sections on a six-column bento grid, with five
   hand-written SVG charts (arc gauge, line-with-target, forgetting curve, stacked area,
   bar rows). Note this reinstates the forgetting-curve panel that was deliberately
   deleted earlier.
2. **Cards** — two panes, an editor that never moves when you select another card.
3. **Reader** — a screen, not a modal: **continuous vertical scroll** (Naz overrode the
   earlier page-at-a-time decision), two collapsible rails (thumbnails, notes), a
   fullscreen control that collapses the nav and both rails, and blackout/annotation
   boxes **re-measured from text rects** via ResizeObserver instead of stored 0–1
   coordinates. ⚠️ Discuss before starting: text-rect measurement needs a pdf.js text
   layer and cannot work on scanned pages, which is exactly where blackouts matter most.
4. **The four motion moments**, last: 5/5-only grade reveal, session complete, streak
   dots, ingest topic list.

Deviations already agreed: **no `f` logo tile** (Naz asked for it removed; the design
reinstates it) and **no dot-grid page texture** (removed at Naz's request).

## Other open threads

- **Launchpad Challenge — deadline Aug 2.** Needs: ship the current build to Zo, a
  `/api/plan.json`-driven Google Calendar automation writing study blocks, and a 2–3
  minute demo recording.
- **One real session exists, and it is not enough.** Session 15 (2026-07-29) graded
  four cards on `Functions Intro` at marks 1/3/4/3 — that is what the session report
  was verified against. But `answer_log` holds only **4 timed answers** and the
  personal baseline needs **6**, so `seconds_per_card()` still returns its 84s
  assumption and the report says "no personal baseline yet". Retrieval fluency needs
  6 too, and calibration needs confidence-tagged answers (that session logged none).
  Two more sessions, answered with the confidence buttons, close all three.
- Two Python lectures have a "Course Logistics" topic that predates the content/general
  flag and could be reflagged.

## Conventions

Commit per feature with an explanatory message. Verify live in the browser preview
before claiming anything works, and remove test artifacts from the real database
afterwards. Never claim numbers that weren't measured. All LLM spend is on Naz's own
OpenAI key — keep test calls minimal. Offline suites (nine of them run offline; `check_ingest` needs the API key) live in `tests/` and
must pass before a commit.
