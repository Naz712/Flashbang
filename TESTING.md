# Flashbang — Test & Eval Log

Running record of every check suite, live end-to-end test, benchmark, and the
bugs they caught. Offline checks are repeatable any time; live tests hit the
OpenAI API and are logged with their date and result.

## How to run the offline checks

```
.\flashbang\Scripts\python.exe tests\check_db.py        # schema, FKs, cascades, undo, answer log
.\flashbang\Scripts\python.exe tests\check_mastery.py   # decay math, relearning statuses
.\flashbang\Scripts\python.exe tests\check_search.py    # cosine ranking (stubbed embeddings)
.\flashbang\Scripts\python.exe tests\check_router.py    # pin fast-path + keyword routing
.\flashbang\Scripts\python.exe tests\check_planning.py  # schedule packing, statuses, stats
.\flashbang\Scripts\python.exe tests\check_ingest.py <pdf>   # LIVE: real-PDF ingestion (needs API key)
```

All five offline suites: **PASSING** as of 2026-07-21.

## Offline check coverage

| Suite | Asserts |
|---|---|
| check_db | FK enforcement (orphan inserts fail), course→cards cascade, study-log survival with NULL refs, full-ISO timestamps, card FKs derived from topic, review/undo round-trip (one-level snapshot), derived session card-counts, answer_log calibration math (sure 100% / unsure 50%), 85%-rule topic accuracy (83% over 6 answers, min-N threshold), session accuracy column |
| check_mastery | R(0)=1; R(interval)=0.75; monotone decay; never-reviewed=0; interval_days=0 safe; mean-based topic mastery; **successive relearning**: 1 recall = in_progress, 2 recalls = covered; est-minutes-weighted completion (hand-computed cases) |
| check_search | Ranking with hand-made vectors, min_score filter, topic-scoped filter, citation join columns |
| check_router | Strict pin: answer attempts never re-routed; "end review session" stays with review (it must close the log); escape+intent leaves; soft pin: approvals stay, review asks escape; ingest-verb > review-word > bare-.pdf precedence |
| check_planning | Daily budget respected, urgent-first ordering, 90-min block split across days with zero minutes lost, MIN_CHUNK floor, done/missed/planned derivation, replan replaces future but keeps history, streak/weekly stats |

## Live test log

### 2026-07-17 — provider port smoke tests (OpenAI)
- grade_answer on gpt-4o-mini: coherent 0–5 grade + feedback. Noted slight
  strictness (full paraphrase scored 4/5 — leniency rule added later).
- Embeddings: 1536-dim vector returned. Router Haiku-replacement classify:
  "can you tidy up my card collection" → organizer. ✅

### 2026-07-17 — check_ingest on Lecture3_Transformer1.pdf (16 pages)
- **BUG FOUND**: gpt-4o returned overlapping topic ranges (p.4-5 then p.5-8)
  despite prompt constraints. **Fix**: `_normalize_ranges()` repairs ranges
  deterministically (commit 588e46d). Re-run: PASSED. 6/16 pages used vision
  fallback successfully via gpt-4o PDF input.
- Segmentation is non-deterministic run to run (5 topics vs 3) — acceptable,
  the approval gate exists for this.

### 2026-07-17 — 4-turn scripted conversation (orchestrator, OpenAI loop)
- planner progress report (35.9%, flagged overdue topic) ✅
- review session: pin held through an answer attempt; grade 4/5; SM-2
  scheduled 15d; end_session derived cards_reviewed=1 from DB ✅

### 2026-07-17 — planner propose→approve→save flow
- **BUG FOUND**: "looks good, save it" misrouted to organizer, which had no
  save tool and **claimed success while saving nothing**. **Fixes**: planner
  soft-pin during proposal flow + integrity rule in all four agent prompts
  (never claim success without a tool result). Re-run: 5 entries saved,
  statuses derive correctly (commit 366b163).

### 2026-07-20 — review flow through the web UI
- **BUG FOUND**: "Review my due cards in Lecture3.pdf" routed to ingestion
  (bare `.pdf` outranked "review"). **Fix**: keyword precedence ingest-verb >
  review > weak-.pdf.
- **BUG FOUND**: model passed a filename string as pdf_id → SQL matched
  nothing → "no cards due" + dangling open session. **Fixes**: integer
  validation on all id args with instructive error; UI passes explicit ids;
  agent told to close empty sessions.
- Re-run: 10 due cards found, question shown, confidence "unsure" tagged,
  grade chip "3/5 · interval 6d → 14d · next 2026-08-03" with undo button,
  calibration note ("you did better than you expected"), dashboard updated
  mid-session (due 10→9, completion 33→36%, topic mastery 54→63%). ✅

### 2026-07-21 — RB2302_Part_1_Slides.pdf (242 pages, 30.5 MB)
- Local extraction: 242 pages, 179,687 chars, **0 sparse pages → zero vision
  calls**. Segmentation (2 chunks): 14 topics, contiguous 1–242, 8.4h total.
- Streaming statuses displayed live ("Reading the PDF page by page…",
  "Splitting into topics…").
- **BUG FOUND**: typewriter froze mid-word — requestAnimationFrame pauses in
  unfocused tabs. **Fix**: setInterval with 4s hard cap; instant render in
  hidden tabs (commit 09ad7a2).
- Pretest first live run (user-driven): 5 questions spanning the deck,
  answers revealed after attempts, no grading, graceful handling of an
  off-script question mid-pretest. ✅
- Concept-extraction quality note: intro topic (pages 1–8) produced
  course-admin "concepts" (schedule, assessment). Prompt now skips logistics
  content by default (commit aab93a0).

### 2026-07-21 — cs2030de batch (5 decks)
- 37+14+28+23+19 pages → 6/4/9/5/7 topics, 8.3h total. Vision used on only
  10 decorative title pages across the batch. All ranges contiguous. ✅

### 2026-07-21 — topic page viewer
- Clicked "Backpropagation" (p.102–117) → modal rendered exactly 16 canvases,
  labeled page 102…117, bounded start/stop. pdf.js path; text fallback
  untested live (no pasted-text source in DB yet). ✅

### 2026-07-21 — Cards page + progress sorting (web UI)
- Cards tab: filters populated (2 courses / 6 docs / 45 topics), inline edit
  round-trip verified (answer edited in UI → persisted in DB), move-to-topic
  select and delete present. ✅
- Progress sort control: weakest / strongest / most due / by name / newest
  reorder the per-course pdf cards; choice persists in localStorage. ✅
- **DATA BUG FOUND**: orphan duplicate pdf row (RB2302 status=pending, 0
  topics) left over from the first chat-ingest turn calling read_pdf twice.
  Orphan deleted. Watch: ingestion agent occasionally re-calls read_pdf.

### 2026-07-21 — structured grading feedback (research-backed format)
Grading replies restructured per the feedback literature; every graded answer
now renders six sections:
- **YOU HAD / THE GAP** — task-level "how am I going", specific, no vague
  praise (Hattie & Timperley 2007; Shute 2008)
- **MODEL ANSWER** — always shown (correct-answer feedback beats
  right/wrong-only)
- **WHY** — one-sentence elaboration for transfer (elaborated feedback)
- **REMEMBER** — feed-forward retrieval hook ("where to next")
- **calibration note** — confidence vs performance; confident errors flagged
  per the hypercorrection effect (Butterfield & Metcalfe 2001)
Implementation: grading.py returns structured JSON {quality, right, gap, why,
hook, calibration} + the stored answer; confidence passes through the
grade_answer tool; agent told not to restate the card's content.
Verified live: unsure + partially-correct answer → GRADE 3/5 amber card with
all sections populated and calibration "unsure but mostly correct". ✅

### 2026-07-26 — response-latency tracking + retrieval fluency metric
Client stamps when a question card renders (`[CARD n/m · topic]` marker) and
sends `latency_ms` with the next message; server keeps it only for turns that
produce a grade (same first-grade-of-turn rule as confidence), stores it in
`answer_log.latency_ms`. New Progress panel "RETRIEVAL FLUENCY · 28 DAYS":
2×2 of fast/slow (vs personal median — typing speed and question length wash
out) × right/wrong, plus median time-to-correct. Needs 6+ timed answers.
Research basis: speed of correct recall predicts retention beyond accuracy
(Benjamin & Bjork 1996); slow-but-right cards are the ones to keep spacing.
- check_db extended: latency round-trip + untimed-answers-stay-NULL. All five
  offline suites PASSING.
- Verified live (no API spend): fetch stubbed with a fake SSE reply — turn
  without a question card sent `latency_ms: null`; card marker armed the
  clock; answer sent 1.3s later carried `latency_ms: 1378`. ✅ Panel verified
  in both empty ("0 of 6 timed answers") and populated states (injected
  display data: 42% fluent, quad bars). ✅
- Known approximations: latency includes typing time (median split absorbs
  it); a mid-card detour question inflates that one measurement; answers
  after a page reload go untimed (NULL, excluded).

## Benchmarks — card creation (2026-07-21, gpt-4o)

| Stage | 2-page topic | 7-page topic |
|---|---|---|
| Concept extraction (1 call) | 6.5s → 2 concepts | 10.3s → 6 concepts |
| Save + embed | 5.1s | 3.4s |
| Card generation (1 call/concept) | 5.1s → 7 cards | 16.8s → 27 cards |
| DB inserts | 0.2s | 0.6s |
| **Total** | **16.9s** | **31.0s** |

- Bottleneck: per-concept generation calls, ~2.5–2.8s each (sequential).
- Projection: typical topic 30–60s; a 14-topic 242-page deck ≈ 10–12 min,
  150–250 cards.
- Available optimizations (not yet applied): batch embeddings into one API
  call (−3–5s/topic); parallelize per-concept generation (~3× faster).

## Cost & time per request (est. 2026-07-21, standard OpenAI rates)

Rates assumed: gpt-4o $2.50/M in + $10/M out; gpt-4o-mini $0.15/$0.60;
text-embedding-3-small $0.02/M. Check platform.openai.com/usage for actuals.

| Request | Model | Tokens in/out | Time | Est. cost |
|---|---|---|---|---|
| Router classify | 4o-mini | 250 / 1 | <1s | ~$0.0001 (pin/keyword layers make most turns free) |
| Answer grading | 4o-mini | 700 / 80 | 1–2s | ~$0.0002 |
| Embedding per concept | emb-3-small | ~200 | 0.5–2.5s | ~$0.00001 |
| Chat turn (agent+tools) | 4o | 3–15k / 200–500 ×2–3 calls | 5–15s | $0.02–0.05 |
| Concept extraction/topic | 4o | 2–6k / 1–4k | 6–10s | $0.01–0.05 |
| Card gen per concept | 4o | 1.2k / 400–700 | 2.5–2.8s | ~$0.01 |
| Segmentation per chunk | 4o | ~25k / ~800 | 25–35s | ~$0.07 |
| Vision batch (≤8 pages) | 4o | 10–15k / ≤8k | 15–40s | $0.05–0.10 |

Measured real operations: RB2302 ingest ≈ $0.15 / 90s · cs2030de batch ≈
$0.20–0.25 / 4min · cards per topic ≈ $0.05–0.10 / 17–31s · full 14-topic
card build ≈ $1–1.50 / 10–12min · 10-card review session ≈ $0.25–0.40.

Cost profile: reviews are the dominant RECURRING cost (history grows each
turn and is re-sent to gpt-4o); ingestion is a cheap one-off. Levers if
credits tighten: trim session history after each completed card, or set
OPENAI_MAIN_MODEL=gpt-4o-mini. Typical usage ≈ $8–12/month equivalent.

## Known approximations (by design)

- Weekly completion delta re-runs decay math as of 7 days ago; only each
  card's latest review is stored, so recently-reviewed cards read as "new
  since last week" (delta biases slightly positive).
- Per-topic time-spent divides each session's minutes evenly across the
  topics it touched.
- Session recall % comes from grades observed by the server during the
  session window.
- Calibration chart and 85%-rule flags need data: confidence-tagged answers,
  and ≥6 graded answers per topic in 28 days, respectively.

## Results appendix (raw outputs)

### Offline suite run — 2026-07-21

```
check_db:       ALL PASSED
check_mastery:  ALL PASSED
check_search:   ALL PASSED
check_router:   ALL PASSED (keyword + pin layers)
check_planning: ALL PASSED
```

### RB2302_Part_1_Slides.pdf — saved topic split (242 pages, 8.4h)

```
p.1-8     ~25 min  Introduction to Neural Networks
p.9-40    ~20 min  Basic Mathematical Concepts for Neural Networks
p.41-68   ~35 min  Gradient Descent and Optimization
p.69-91   ~40 min  Perceptron Learning Algorithm
p.92-101  ~30 min  Multilayer Perceptrons (MLP)
p.102-117 ~40 min  Backpropagation
p.118-146 ~70 min  Classification and Regression
p.147-154 ~25 min  Support Vector Machines and Applications
p.155-176 ~50 min  Convolutional Neural Networks (CNNs)
p.177-196 ~45 min  Learning in Convolutional Neural Networks
p.197-206 ~40 min  Recurrent Neural Networks (RNNs) and Applications
p.207-219 ~35 min  Long Short-Term Memory (LSTM)
p.220-241 ~45 min  Training Techniques and Optimizations
p.242     ~5 min   Historical Overview
```

### cs2030de batch — saved topic splits (5 decks, 8.3h)

```
Chapter 2 Data Encapsulation v1.pdf — 37 pages, vision p.[1], 2.5h
  p.1-6    ~25 min  Access Modifiers
  p.7-13   ~30 min  Data Encapsulation
  p.14-19  ~25 min  Object Composition
  p.20-24  ~25 min  Object Aggregation
  p.25-30  ~25 min  Java Private Methods
  p.31-37  ~20 min  Creating and Using Java Packages

Chapter 3 Inheritance (Annexure)_publish2.pdf — 14 pages, vision p.[1,4,14], 0.8h
  p.1-4    ~10 min  Introduction to Digital Circuit Design using Inheritance
  p.5-7    ~10 min  Design Flow of Logic Gates with Alternative Solutions
  p.8-12   ~20 min  Digital Circuit Simulation: Implementation and Testing
  p.13-14  ~5 min   Challenges and Alternative Design Choices in Digital Circuit Simulation

Chapter 3 Inheritance v4.pdf — 28 pages, vision p.[1,17,28], 1.7h
  p.1-4    ~10 min  Introduction to Inheritance
  p.5-8    ~12 min  Basic Inheritance Example and Child Class Accessibility
  p.9-11   ~10 min  Single Parent - Single Child Inheritance Examples
  p.12-17  ~20 min  Protected Variables and Methods
  p.18-19  ~10 min  Method Overriding and the @Override Annotation
  p.20-21  ~12 min  Abstract Classes and Methods
  p.22-25  ~20 min  Multiple Children and Inheritance Applications
  p.26     ~5 min   Limitations of Multiple Inheritance in Java
  p.27-28  ~5 min   DIY Application: Currency Converter

Chapter 4 Interfaces v3 Part 2.pdf — 23 pages, vision p.[1,2,23], 2.0h
  p.1-6    ~25 min  Introduction to Java Interfaces
  p.7-13   ~35 min  Properties and Usage of Java Interfaces
  p.14-19  ~30 min  Design Patterns with Interfaces
  p.20-21  ~20 min  Examples and Tutorials on Java Interfaces
  p.22-23  ~10 min  Summary of Java Interfaces

Chapter 4 Polymorphism v3 Part 1.pdf — 19 pages, vision p.[1,19], 1.3h
  p.1-3    ~10 min  Introduction to Polymorphism
  p.4-5    ~10 min  Examples of Polymorphism
  p.6      ~5 min   Concepts of Polymorphism
  p.7-8    ~10 min  Compile-time and Runtime Polymorphism
  p.9-13   ~20 min  Polymorphism & Object Creation
  p.14-17  ~15 min  Practical Exercises and Code Examples
  p.18-19  ~10 min  Additional Exercises and Concept Review
```

### Card-creation benchmark — raw output (2026-07-21)

```
=== Method Overriding and the @Override Annotation (2 pages, est 10 min) ===
  extract_concepts:     6.5s  -> 2 concepts
  save+embed:           5.1s  -> 2 notes embedded
  generate_cards:       5.1s  -> 7 cards (2.5s per concept call)
  insert cards:         0.2s
  TOTAL:               16.9s for 7 cards (2.4s per card)

=== Data Encapsulation (7 pages, est 30 min) ===
  extract_concepts:    10.3s  -> 6 concepts
  save+embed:           3.4s  -> 6 notes embedded
  generate_cards:      16.8s  -> 27 cards (2.8s per concept call)
  insert cards:         0.6s
  TOTAL:               31.0s for 27 cards (1.1s per card)
```

Sample generated cards (saved for real, due next day):

```
Q: What is method overriding in Java?
A: Method overriding in Java occurs when a subclass defines a method with the
   same name, parameters, and return type as one in its superclass.

Q: Is the @Override annotation necessary for method overriding to work in Java?
A: No, method overriding works in Java even without explicitly using @Override.

Q: What role do access modifiers play in data encapsulation?
A: Access modifiers control access to class members and methods, preventing
   unauthorized access.

Q: Why should certain internal representations be hidden in data encapsulation?
A: Hiding internal representations prevents accidental access from outside,
   safeguarding data integrity.
```

### Live review-flow verification — 2026-07-20 (web UI)

```
user:  Review my due cards in "Lecture3_Transformer1.pdf" (pdf_id 1)
agent: You have 10 cards due... Card 1: What does this concept do?
user:  [confidence: unsure] it explains what the concept does in the demo answer
agent: Grade 3/5 · interval 6d → 14d · next 2026-08-03 [undo]
       ...Your confidence level was "unsure," and you did better than you expected.
dashboard (live, mid-session): due 10 → 9 · completion 33% → 36% · topic 54% → 63%
```

## Not yet exercised live

- Cram mode end-to-end through the UI (prompt-level logic tested only in
  spec review).
- Successive-relearning re-ask loop within a real session (unit math tested;
  agent behavior is prompt-driven).
- Text-source ingestion path (create_text_source) and the viewer's
  extracted-text fallback.
- Insights save/fetch through the new UI.
