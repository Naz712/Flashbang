# Flashbang — continuation brief

Paste this into a new chat to pick up where the last one left off. First move
each session: `git log origin/frameworks..HEAD` — a brief can say "done" while
the remote disagrees.

## Where the code is

- **Primary: `C:\Users\Nazzoom\Desktop\Flashbang-frameworks`** (branch `frameworks`,
  port 5002). Run: `.\flashbang\Scripts\python.exe server.py`
- **Frozen reference: `C:\Users\Nazzoom\Desktop\Flashbang`** (branch `master`, port
  5001) — the original hand-rolled build, kept for the A/B story. Do not develop here.
- **Remote:** private repo `github.com/Naz712/Flashbang` (push regularly — sessions
  have ended 19 commits ahead).
- **Deployed:** `https://flashbang-nazzoom.zo.computer` — badly out of date, predates
  the de-agenting. Updating means asking Zo's agent to swap the hosted-service slot to
  SSH, scp, swap back.

## What the app is

A de-agented study app. The server deals reviews, buttons do ingest/card-gen, one
fast-tier call grades each typed answer, FSRS reschedules. One scoped assistant lives
in a corner bubble. Twelve offline suites in `tests/` must pass before any commit.
Every model call logs to the spend tracker; never claim numbers that weren't measured;
test artifacts get deleted from the real DB after verification.

**The full loop now:** ingest PDF → topics (boilerplate stripped, 40-page chunk cap) →
primer before reading ("don't go in blind": gist / one analogy with mapping AND where
it breaks / ideas / search links, cached ~$0.0003) → reader (a screen: continuous
scroll, thumbnail + notes rails, fullscreen, blackouts/annotations, reading blocks) →
cards (generate ~$0.04/topic, two-pane editor, paste-import) → review (budget-derived
deal, teaching feedback, ghost-tick schedule footer, session report REPLACES the
transcript) → tutorials (split into leaf questions ~$0.05/paper, tagged with the
course's own topic IDS, flags survive re-split, answers retrieved by PAGE never
extracted, inline-solutions handled, retag $0.0003) → NotebookLM round-trip (copy
examiner prompt with embedded ids → quiz there → paste reply → external_reviews decay
like a first recall, only ever RAISE the display, never touch FSRS or the exam
projection) → analytics (6 tabs, honest gates) with SPEND band.

**Data loaded:** Python (13 lectures, 96 topics, 4 cards reviewed once), cs2030de
(5 chapters), RB2302 (242-page deck → 41 topics, 6 tutorials → 79 questions all
tagged, 17 cards unreviewed). ~$0.75 total spend to date.

## Design system (handoff at `~/Downloads/flashbang Design System`)

Phases 1–6a ALL DONE: tokens/shell/Home (`ee025bb`), course page (`b264616`), Review
in three parts (`4915b3c` `c076e0a` `19a9648`), Analytics (`ea2862c`), Cards
(`365cd95`), reader-as-screen (`cec9f74`). Each converted screen deleted its legacy
CSS block. The four motion moments exist in the token layer and are mostly wired
(5/5 reveal, report-in, week dots, ingest topic list).

**Remaining: phase 6b — hybrid blackout measurement.** Agreed design: decide mode
per BOX at creation (does the drawn rect intersect pdf.js word rects?), store the
mode never recompute it, reuse the ingest sparse-text threshold, `occlusions` gains a
`mode` column defaulting to `norm` (no backfill needed). Settled — build, don't
re-discuss.

Rules with teeth: colour = mastery or the one cobalt action, never decoration; every
bar ships with its number; the em dash guards RETRIEVAL not card existence (0% with
unreviewed cards is a lie; 0% after decay is a measurement); every derived number
carries its evidence line; no shadows; nothing rotated; only 5/5 animates.

## Traps learned the hard way (do not relearn)

- `save_topics` APPENDS — re-segmenting a pdf doubles its topics; delete stale rows.
- Chunking by chars alone put 214 slide pages in one segmentation call → one giant
  topic. `SEGMENT_CHUNK_PAGES = 40` guards it now.
- Slide decks repeat a nav strip on every page (37% of RB2302's text) —
  `strip_boilerplate` handles it at ingest.
- pymupdf4llm formats nicer but DROPS equations on these files; pypdf keeps them
  mangled-but-present. Tested and rejected — don't revisit without retesting.
- The gap list is quality<=3 but scheduling extends at >=3 — conflating them made the
  session report contradict itself once.
- Verifying UI by starting/ending sessions leaves empty study_sessions rows — delete
  them after.
- The splitter/tagger are model calls not regex, on purpose: formats vary per module.
  Tags are echoed topic IDS from a supplied list, never free text.

## Open threads

- **Push.** Sessions keep ending ahead of origin.
- **6b** (above), then the design system is done.
- **Review volume:** 4 timed answers logged; the personal sec/card baseline needs 6,
  calibration needs confidence-tagged answers, fluency needs 6. Two real sessions
  with the confidence buttons close all three. 17 RB2302 cards come due tomorrow.
- **Zo deploy is stale** and the Launchpad demo recording never happened (deadline
  was Aug 2).
- Agnes/GMI free models: the hook exists (`OPENAI_BASE_URL` + model env vars in
  .env), untested — needs the model names from their docs and one cheap trial.

## Conventions

Commit per feature with an explanatory message. Verify live in the browser preview
before claiming anything works; remove test artifacts from the real database after.
Never claim unmeasured numbers. All spend is on Naz's own OpenAI key — keep test
calls minimal. Twelve offline suites must pass before a commit.
