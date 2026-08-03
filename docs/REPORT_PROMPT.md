# Paste this into a new chat to write the Launchpad report

---

I'm finalizing my Launchpad AI Challenge submission for **Flashbang**, my study
app at `C:\Users\Nazzoom\Desktop\Flashbang-main` (branch `frameworks`, also on
GitHub `Naz712/Flashbang`). Read `docs/CONTINUE.md` first for orientation, then
work from these two drafts:

- `docs/SUBMISSION.md` — a five-pillar write-up draft (~940 words)
- `docs/DEMO_SCRIPT.md` — a 3-minute demo shot list

Your job: turn the draft into my final ≤1,000-word write-up.

**Rules that matter (from the judging brief):**
- Five pillars as section headings: Problem, Approach, Evidence, Constraints,
  Honesty & Trajectory. Scored 1–5 each by domain experts.
- "Evidence appropriate to the claim" — a modest claim proven beats a grand
  claim asserted. Every number must be a measurement; never round a claim up.
- Appendices don't count against the 1,000 words.

**Refresh the stale numbers before anything else.** The draft was written
before my latest study sessions and the Zo deployment. Do not trust its
figures — re-derive them:
1. Run the app (`.\flashbang\Scripts\python.exe server.py`, port 5002) and
   read `/api/state` — the SPEND band and `budget.sec_per_card` are the truth.
   The draft says "4 of 6 timed answers, 84s assumed"; the baseline has since
   become MEASURED (53s/card) because I ran real sessions. That upgrade is
   itself evidence — use it.
2. `git log --oneline` for the commit trail; `tests/` for the suite count
   (should be 12 — verify).
3. New facts the draft predates: deployed to my Zo Computer machine
   (`/home/workspace/flashbang-main`, supervised service, login-gated),
   review-card UI compaction, the rebuilt NotebookLM-grounded tutor prompt.

**Voice:** first person, mine. Plain sentences. No marketing adjectives. Where
the draft says something I didn't measure, cut it or measure it.

**What I still do myself (remind me at the end):** record the demo video from
`docs/DEMO_SCRIPT.md`, make the repo public or grant judge access, complete
the registration profile.

Keep every claim traceable: if a judge asks "how do you know?", the answer
must be in the repo — a spend-tracker row, a test, or a commit message.
