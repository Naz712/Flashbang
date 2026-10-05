# Interview cheat sheet — explaining Flashbang

Tell decisions, not features. Lead with the insight, keep numbers exact,
volunteer the weaknesses before they ask.

## The 30-second opener (always start here)

> Flashbang is a study app that closes the loop AI chat leaves open. Chat
> explains, but explanation is consumption — retrieval is what builds
> memory, and nothing records whether you could actually recall anything.
> My app ingests real lecture PDFs, generates flashcards tied to pages and
> topics, grades my TYPED answers with one small model call, and schedules
> reviews with FSRS. Every readiness number is traceable to a measurement —
> and the whole thing ran on about a dollar of API spend.

Problem → mechanism → the two values (honesty, cost). Four sentences.

## The 2-minute walkthrough (walk the loop, not the screens)

1. **Ingest.** "A 242-page deck became 41 topics with page ranges for
   $0.17. The interesting part happens before the model sees anything:
   the nav strip repeated on every slide was 37% of the text — stripped
   deterministically. Model calls only where formats genuinely vary."
2. **Review.** "The server deals due cards within a daily budget. I type
   the answer — typed, not self-graded, because typing is the retrieval
   act — and one fast-tier call grades it: what I had, the gap, a memory
   hook. $0.0002 per answer. FSRS reschedules from the grade."
3. **Evidence.** "Metrics are gated on real data. Never-reviewed cards show
   an em-dash, not 0%. My pace showed 'assumed' until six timed answers
   existed, then flipped to measured. An app that lies about readiness is
   worse than no app."
4. **The hub idea.** "I didn't rebuild tutoring. The app compiles my gaps
   into a prompt for Claude/NotebookLM; NotebookLM's graded reply parses
   back because the prompt embeds my question IDs. Expensive tools do
   explanation; the evidence comes home to the schedule."

## THE story: de-agenting (tell this one if you tell only one)

> The first build was four LangGraph agents behind a router. It felt
> sophisticated. Then I added a spend tracker logging every model call,
> and the data said the agents added cost and latency and no value:
> reviewing is dealing due cards — a database query; ingesting is a
> pipeline; card generation is a button. I deleted the agent layer. Same
> features, roughly 1/100th the session cost, faster. The frozen agent
> build is still on its own branch with its spend logs, so the comparison
> is checkable. Lesson: a model call where formats genuinely vary, code
> everywhere else.

If asked what LangGraph is for: "Workflows where a model must choose the
path at runtime. I used it, measured it, and found my paths were static —
every 'decision' the graph made was either deterministic or belonged to
the user. Knowing when NOT to use an agent framework is the skill."

## Negative results kept in the repo (credibility ammunition)

- AI-drawn primer diagrams: built, measured $0.0004–$0.0117, didn't teach
  well, removed.
- pymupdf4llm: benchmarked better, dropped equations on my files, rejected.
- Hand-rolled SM-2 scheduler: lost an A/B to the FSRS library, replaced.
- The agent build itself: measured, dismantled, kept frozen on `master`.

"I keep my failures in the repo" — rare and checkable.

## Loaded answers for likely questions

- **Stack?** Flask, vanilla JS, SQLite, FSRS library, two OpenAI tiers
  (main = segmentation, fast = grading). "Boring on purpose — the novelty
  budget went to the evidence model, not the framework."
- **Why not Anki?** "Right scheduler, zero connection to my materials;
  every card is manual. I kept its science (FSRS) and automated the part
  that makes people quit."
- **Why not self-grade / autocomplete?** "Autocomplete exists everywhere
  EXCEPT the review answer box — autofill there would manufacture fake
  retention data." (One detail that proves the principle.)
- **How do you know <any number>?** "Spend-tracker row, test suite, or
  commit message." 12 offline suites run without an API key.
- **What's weak?** (volunteer first) Equation extraction is ugly —
  page-image fallback; tagging had vocabulary gaps (5 of 79 hand-passed);
  single-user by design. Trajectory: a semester of real use is the only
  evaluation that counts.
- **Deployment?** "Runs locally; also deployed on a personal Linux server
  (Zo) as a supervised, login-gated service. SQLite + file uploads made
  the move one scp, plus one trap: the DB path had to be module-anchored
  or a moved install silently creates an empty database — the worst
  failure mode is one that doesn't error."

## Numbers to say exactly (never round up)

| Number | What it is |
|---|---|
| $1.06 | all-time spend: 4 courses, 24 documents, 6 tutorials, 86 calls |
| $0.00023 / 2.5–3.6s | grading one typed answer |
| $0.17 / ~4 min / 41 topics | the 242-page deck |
| 37% | boilerplate stripped before any model call |
| 79 questions, 74 auto-tagged | six real tutorial sheets, $0.32 |
| 51s measured vs 84s assumed | per-card pace after real sessions |
| ~100× | de-agenting session-cost saving |
| 12 | offline test suites, all passing at head |

## Delivery notes

- Insight first, tech second: the tech is defensible, the insight is
  memorable.
- Precise and modest beats impressive: be the candidate whose numbers
  survive scrutiny.
- Job interview (not Launchpad): compress the honesty pillar to one line —
  "I measured my own architecture and deleted half of it" — and spend the
  saved time on their domain.
