"""py-fsrs adapter — replaces the hand-rolled SM-2 (sm2.py, kept for the
reference board). FSRS is the scheduler behind modern Anki: each card carries
a learned *stability* (days until predicted recall drops to 90%) and
*difficulty*, updated per review by a research-fitted model.

Configuration choices (settled after the A/B eval journey — 0.75 stretched
intervals to months and was reverted; 0.95 chosen for exam-driven study):
- desired_retention=0.95: reviews land when predicted recall falls to 95% —
  Anki-like ladder (steady Good ≈ 1, 3, 8, 19, 43d), a high everyday floor
  for exam season, ~1.5× the workload of the 0.90 default.
- maximum_interval=180: no card silently disappears for more than a semester.
- learning_steps=() / relearning_steps=(): no intra-day micro-steps; this is
  a study app reviewed in daily sessions, and empty steps keep scheduling
  deterministic for tests.
- enable_fuzzing=False: deterministic intervals (tests + honest A/B against
  the SM-2 original).
"""

from datetime import datetime, timezone
from fsrs import Scheduler, Card, Rating, State

scheduler = Scheduler(
    desired_retention=0.95,
    maximum_interval=180,
    learning_steps=(),
    relearning_steps=(),
    enable_fuzzing=False,
)

# our 0-5 grading quality -> FSRS's four ratings
QUALITY_TO_RATING = {0: Rating.Again, 1: Rating.Again, 2: Rating.Again,
                     3: Rating.Hard, 4: Rating.Good, 5: Rating.Easy}


def _to_utc(iso_local):
    """Naive local ISO string -> aware UTC datetime (py-fsrs requires UTC)."""
    if not iso_local:
        return None
    return datetime.fromisoformat(iso_local).astimezone(timezone.utc)


def _to_local_iso(dt_utc):
    return dt_utc.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def card_from_row(row):
    """Rebuild an FSRS Card from a DB row. Legacy cards (reviewed under SM-2,
    no stability yet) are seeded from their SM-2 interval so migration is
    lazy and loss-free; brand-new cards start fresh."""
    if row["stability"] is not None:
        return Card(state=State(row["fsrs_state"] or int(State.Review)),
                    stability=row["stability"],
                    difficulty=row["difficulty"],
                    due=_to_utc(row["next_review"]) or datetime.now(timezone.utc),
                    last_review=_to_utc(row["last_reviewed_at"]))
    if row["last_reviewed_at"]:
        # legacy SM-2 card: its interval approximates a 75%-retention horizon
        return Card(state=State.Review,
                    stability=float(max(row["interval_days"], 1)),
                    difficulty=5.0,
                    due=_to_utc(row["next_review"]) or datetime.now(timezone.utc),
                    last_review=_to_utc(row["last_reviewed_at"]))
    return Card()


def review(row, quality, now=None):
    """Run one FSRS review. Returns the fields to persist."""
    now_utc = (now.astimezone(timezone.utc) if now else datetime.now(timezone.utc))
    card = card_from_row(row)
    card, _log = scheduler.review_card(card, QUALITY_TO_RATING[quality],
                                       review_datetime=now_utc)
    interval_days = max(0, round((card.due - now_utc).total_seconds() / 86400))
    return {
        "stability": round(card.stability, 4),
        "difficulty": round(card.difficulty, 4),
        "fsrs_state": int(card.state),
        "next_review": _to_local_iso(card.due),
        "interval_days": interval_days,
    }


def simulate_forward(row, exam_dt, max_reviews=50):
    """Project a card to exam day assuming every due review happens (Good).
    Returns (stability, last_review_iso) at the final state before the exam —
    used by the exam-readiness metric."""
    exam_utc = exam_dt.astimezone(timezone.utc)
    card = card_from_row(row)
    if card.due is None:
        return None, None
    for _ in range(max_reviews):
        if card.due >= exam_utc:
            break
        card, _log = scheduler.review_card(card, Rating.Good, review_datetime=card.due)
    last = _to_local_iso(card.last_review) if card.last_review else None
    return (card.stability, last)
