# Flashbang — Launchpad AI Challenge write-up

*Final. Every number below is a measurement from the app's own spend tracker,
test logs, or timed runs on real course material. Where something is an
estimate, it says so. Appendix B maps each claim to where a judge can check
it.*

## 1. Problem

My old study loop: upload the lecture deck to Claude or NotebookLM and ask
for an explanation. It works for one session. When the chat ends the
evidence evaporates: nothing records what I covered, what I could recall
unaided, or whether I am on pace.

Existing tools each hold one piece. Claude and NotebookLM: explanation,
no memory, no schedule. Anki: scheduling, but every card is typed by hand,
and my modules' notes vary too much in format to keep up. PDFs, tutorial
sheets and flashcards never meet, so "am I on track" has no answer.

The insight that shaped the design: an AI chat makes passive study feel
more productive while making the loop worse. Explanation is consumption;
retrieval, answering unaided at the right time, is what builds memory.
Flashbang therefore supports those tools instead of replacing them: the
model inside never explains during study. It deals, grades my typed
retrieval, and reschedules. Explanation goes to the tools that do it best;
the graded evidence always comes home.

Success criteria, set before building: one loop from any module's PDF to
scheduled retrieval, no manual transcription; every readiness number
traceable to a measurement, since an app that lies about readiness is worse
than no app; under $1 a week for five modules on my own key.

## 2. Approach

**A hub, not another chat.** Claude and NotebookLM are better tutors than
anything I could rebuild, so Flashbang owns what they cannot: the schedule
and the evidence. A session report compiles my gaps into a tutor prompt for
Claude; an examiner prompt embeds question ids so NotebookLM's graded reply
parses back for $0. In app tutoring, the alternative, re buys explanation.

**The defining decision was removing the agents.** The first build ran four
LangGraph agents and a router; measurement showed they added cost and
latency and no value. Reviewing is dealing due cards, a database query;
ingesting is a pipeline; card generation is a button. Now the server deals,
buttons act, and one fast tier call grades each answer, at roughly one
hundredth of the old session cost. Anki style self grading is free but
loses typed retrieval, teaching feedback and calibration data.

**Model calls only where formats genuinely vary**: segmenting arbitrary
decks, splitting tutorial sheets whose numbering differs per module. Regex,
the alternative, breaks per module by design. Tags echo my own topic ids
from a supplied list, never free text, which cannot join back to the notes.
Everything else is deterministic and $0.

**Scheduling is FSRS, not invented.** My hand rolled SM-2 lost to the FSRS
library on my own reviews; FSRS stayed, re tuned after its default
intervals exploded. Memory research ships as a library; mine would be
complexity as decoration.

**Left out on purpose.** AI drawn primer diagrams: built, measured at
$0.0004 to $0.0117, not good enough to teach, removed. Raster diagrams:
wrong labels at 130 times the cost. Scheduling tutorial questions like
cards: grading cost a filterable pool avoids. One tell: autocomplete exists
everywhere except the review answer box, where autofill would manufacture
fake retention evidence.

## 3. Evidence

All figures come from the in app spend tracker. Samples are small and I say
so: one student's real workload, not a benchmark.

**Grading a typed answer:** $0.00022, 2.5 to 3.6 seconds, structured
feedback plus an FSRS reschedule.

**Review pace is measured, not assumed.** The app hid pace until six timed
answers existed. Real sessions on 2 and 3 August flipped it to measured: 53
seconds per card against the 84 assumed, 58 percent high.

**A real 242 page deck:** $0.17, about 4 minutes, 41 topics. The
boilerplate stripper removed 37 percent of extracted text: 179,687
characters down to 111,757.

**Six real tutorial sheets:** $0.32 total, 6 to 29 seconds each, 79 leaf
questions, 74 auto tagged. Edge cases counted, not hidden: 5 of 79 tags
needed a hand pass; inline solutions excluded; answer pages found for all
79.

**Everything loaded**, 3 courses, 19 documents, 6 tutorials, 42 calls:
**$0.75**.

**Baseline:** the agent loop cost roughly 100 times more per session. That
build is frozen on its own branch with its spend logs.

**Correctness:** 12 offline suites, all passing at head, plus one live
ingestion suite. They rerun without an API key; every commit message states
what it proves.

## 4. Constraints

**The cost curve, not just the chosen point:** $0 for deterministic paths;
$0.0002 for fast tier grading; $0.17 for main tier segmentation; $0.0004 to
$0.0117 for the failed AI diagrams; 130 times that for raster; 100 times
the session cost for agents. Each feature sits at the cheapest point that
meets its need.

**Cost.** About $0.05 per study day, under $1 a week for five modules,
versus $60 to $120 a year for the nearest subscription tool.

**Latency.** Interactive actions land under about 4 seconds. Token heavy
quizzing exports to NotebookLM and parses back for $0; it can only raise a
displayed score, never the FSRS schedule.

**Reliability and honesty.** Vision fallback for sparse pages; the rendered
page for mangled equations; a moved install cannot strand the database.
Metrics lacking data say so: never reviewed cards show an em dash, not a
fake 0 percent.

## 5. Honesty & Trajectory

**Where it breaks today.**

1. Equation text mangles in extraction; the page image is the fallback, but
   titles with maths can be ugly.
2. Tagging has vocabulary gaps: questions saying "tokens" missed a topic
   titled "Encoding"; 5 of 79 needed a hand pass.
3. Calibration is gated: only 2 confidence tagged answers exist, so those
   bands stay empty.
4. Single user, no sync: by design, but a real limit.

**Negative results I kept:** the agent build, measured and dismantled; AI
diagrams, built and removed; pymupdf4llm, which dropped equations,
rejected; my SM-2 scheduler, which lost to FSRS. Each is in the repo, not
hidden.

**With two more weeks:** turn on the calendar automation fed by the app's
read only plan feed; trial the sponsored free model endpoint, hooked,
untested; log enough confidence tagged answers to unlock calibration; begin
the semester of dogfooding, the only evaluation that counts.

---

## Appendix A — submission checklist

1. Repo: `github.com/Naz712/Flashbang` is private. Flip to public or grant
   judge access before submitting.
2. Demo video, 3 minutes maximum. Script in `docs/DEMO_SCRIPT.md`, needs
   recording.
3. This write-up: paste into the submission form.
4. Profile: intro, message to judges, resume.

## Appendix B — where each claim can be checked

| Claim | Evidence in the repo or app |
|---|---|
| $0.75 all time and unit costs | Analytics SPEND tab; `api_spend` rows with per purpose breakdown |
| 53 s per card measured, 84 s assumed before | `/api/state` budget block; timed rows in the answer log |
| 242 page deck to 41 topics for $0.17 | spend rows, purpose segmentation; RB2302 course page |
| 37 percent boilerplate stripped | commit `d698a5c` and its logged before and after counts |
| 6 sheets to 79 questions, 74 auto tagged | spend rows, purpose tutorial split; Tutorials screen; commit `7730612` |
| 12 offline suites pass | `tests/check_*.py`; run them, no API key needed |
| 100 times de-agenting saving | the frozen original build on branch `master`, with its own spend logs |
| External reviews never touch scheduling | `check_external.py`; commit `1243762` |
| SM-2 versus FSRS comparison | the A/B battery in `TESTING.md` |
| Autocomplete absent from the answer box | `static/app.js`, assistant input versus review input |
