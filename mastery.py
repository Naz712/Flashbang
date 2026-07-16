"""Decay and completion math. Pure functions — no database, no API calls.
Everything is computed at read time from card review state; nothing is stored.

Model: Ebbinghaus forgetting curve, R(t) = exp(-t/S).
  t = days since the card was last reviewed
  S = stability, derived from the card's SM-2 interval so that a card sitting
      exactly at its due date has retention DUE_RETENTION. Well-known cards
      (long intervals) decay slowly; fresh or lapsed cards decay fast.
A card that has never been reviewed has retention 0 — creating cards proves
nothing, reviewing is the only evidence of knowledge. Topic coverage falls out
of this rule via the mean, with no separate status weighting.
"""

import math
from datetime import datetime

DUE_RETENTION = 0.75  # retention of a card exactly at its SM-2 due date
_STABILITY_SCALE = -1 / math.log(DUE_RETENTION)  # ≈ 3.476


def card_retention(interval_days, last_reviewed_at, now=None):
    """Retention in [0, 1] for one card. last_reviewed_at is an ISO string or
    None (never reviewed → 0.0)."""
    if not last_reviewed_at:
        return 0.0
    if now is None:
        now = datetime.now()
    elapsed_days = (now - datetime.fromisoformat(last_reviewed_at)).total_seconds() / 86400
    if elapsed_days <= 0:
        return 1.0
    stability = max(interval_days, 1) * _STABILITY_SCALE  # max() guards interval_days=0
    return math.exp(-elapsed_days / stability)


def topic_mastery(cards, now=None):
    """Mean retention over ALL the topic's cards (unreviewed cards count as 0,
    so partial coverage caps the mean). 0.0 if the topic has no cards."""
    if not cards:
        return 0.0
    total = sum(card_retention(c["interval_days"], c["last_reviewed_at"], now) for c in cards)
    return total / len(cards)


def topic_status(cards):
    """Derived, never stored: not_started / in_progress / covered."""
    if not cards:
        return "not_started"
    if all(c["last_reviewed_at"] for c in cards):
        return "covered"
    return "in_progress"


def pdf_completion(topics, cards_by_topic, now=None):
    """Completion % (0-100) of a pdf: topic masteries weighted by est_minutes.
    Unstudied topics drag the number down proportionally to their size."""
    if not topics:
        return 0.0
    weighted_sum = 0.0
    weight_total = 0.0
    for topic in topics:
        weight = topic["est_minutes"] or 1  # fallback weight for un-estimated topics
        mastery = topic_mastery(cards_by_topic.get(topic["id"], []), now)
        weighted_sum += weight * mastery
        weight_total += weight
    return 100 * weighted_sum / weight_total


def build_pdf_report(pdf_row, topics, cards, now=None):
    """Assemble the full dashboard report for one pdf from get_mastery_inputs
    output. Returns plain dicts ready for display."""
    if now is None:
        now = datetime.now()
    now_iso = now.isoformat(timespec="seconds")

    cards_by_topic = {}
    for card in cards:
        cards_by_topic.setdefault(card["topic_id"], []).append(card)

    topic_reports = []
    for topic in topics:
        topic_cards = cards_by_topic.get(topic["id"], [])
        due_cards = [c for c in topic_cards if c["next_review"] <= now_iso]
        next_due = min((c["next_review"] for c in topic_cards), default=None)
        topic_reports.append({
            "id": topic["id"],
            "title": topic["title"],
            "pages": f"{topic['page_start']}-{topic['page_end']}",
            "status": topic_status(topic_cards),
            "mastery_pct": round(100 * topic_mastery(topic_cards, now), 1),
            "est_minutes": topic["est_minutes"],
            "next_due": next_due,
            "cards_total": len(topic_cards),
            "cards_due": len(due_cards),
        })

    return {
        "pdf_id": pdf_row["id"],
        "filename": pdf_row["filename"],
        "completion_pct": round(pdf_completion(topics, cards_by_topic, now), 1),
        "est_total_minutes": pdf_row["est_total_minutes"],
        "total_pages": pdf_row["total_pages"],
        "status": pdf_row["status"],
        "topics": topic_reports,
    }
