"""Revision scheduling. Turns decay deadlines + time estimates into a concrete
day-by-day study plan. The algorithm is deterministic Python (no LLM): the
agent proposes a plan, the user approves/edits, save_study_plan persists it.

Workload items, in priority order:
1. Topics with overdue/soon-due cards → review blocks (minutes scale with the
   number of due cards) placed on or before their due date.
2. Topics with cards never reviewed → first-review blocks.
3. Topics with no cards at all → first-study blocks using the topic's
   est_minutes (reading + making cards).

Items are greedy-packed into daily minute budgets, splitting blocks bigger
than the remaining capacity (minimum split chunk 15 minutes)."""

from datetime import datetime, timedelta
from database import get_topics, get_cards, get_upcoming_reviews

MIN_CHUNK = 15          # minutes; never schedule a sliver smaller than this
REVIEW_MIN_PER_CARD = 2  # minutes per due card in a review block


def _workload(course_id=None, horizon_days=7):
    """Assemble prioritized workload items: {'topic_id','title','minutes','reason','due'}."""
    items = []
    seen_topics = set()

    # 1. due/overdue reviews, most urgent first (get_upcooming is due-date ordered)
    for row in get_upcoming_reviews(days=horizon_days):
        minutes = max(MIN_CHUNK, REVIEW_MIN_PER_CARD * row["cards_due"])
        items.append({
            "topic_id": row["topic_id"], "title": row["title"],
            "minutes": minutes, "due": row["first_due"],
            "reason": f"review {row['cards_due']} due cards",
        })
        seen_topics.add(row["topic_id"])

    # 2 & 3. unstarted work, in document order
    for topic in get_topics(course_id=course_id):
        if topic["id"] in seen_topics:
            continue
        cards = get_cards(topic_id=topic["id"])
        if not cards:
            items.append({
                "topic_id": topic["id"], "title": topic["title"],
                "minutes": max(MIN_CHUNK, topic["est_minutes"] or MIN_CHUNK),
                "due": None, "reason": "first study (read + make cards)",
            })
        elif all(c["last_reviewed_at"] is None for c in cards):
            items.append({
                "topic_id": topic["id"], "title": topic["title"],
                "minutes": max(MIN_CHUNK, REVIEW_MIN_PER_CARD * len(cards)),
                "due": None, "reason": f"first review of {len(cards)} new cards",
            })
    return items


def propose_plan(days=7, minutes_per_day=60, course_id=None, start_date=None):
    """Greedy-pack the workload into daily budgets. Returns entries ready for
    save_study_plan plus totals for display. Saves nothing."""
    if start_date is None:
        start = datetime.now().date()
    else:
        start = datetime.fromisoformat(start_date).date()

    items = _workload(course_id=course_id, horizon_days=days)
    day_capacity = [minutes_per_day] * days
    entries = []
    unscheduled = []

    for item in items:
        remaining = item["minutes"]
        for day_index in range(days):
            if remaining <= 0:
                break
            capacity = day_capacity[day_index]
            if capacity < MIN_CHUNK:
                continue
            chunk = min(remaining, capacity)
            # don't leave a stranded sliver below MIN_CHUNK for the next day
            if 0 < remaining - chunk < MIN_CHUNK:
                chunk = remaining if chunk + MIN_CHUNK > remaining else chunk
            chunk = max(chunk, min(MIN_CHUNK, remaining))
            if chunk > capacity:
                continue
            entries.append({
                "topic_id": item["topic_id"],
                "topic_title": item["title"],
                "plan_date": (start + timedelta(days=day_index)).isoformat(),
                "minutes": chunk,
                "reason": item["reason"],
            })
            day_capacity[day_index] -= chunk
            remaining -= chunk
        if remaining > 0:
            unscheduled.append({"title": item["title"], "minutes": remaining,
                                "reason": item["reason"]})

    return {
        "entries": entries,
        "total_minutes": sum(e["minutes"] for e in entries),
        "days": days,
        "minutes_per_day": minutes_per_day,
        "unscheduled": unscheduled,   # didn't fit the budget — surfaced, never dropped silently
    }
