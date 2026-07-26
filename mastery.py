"""Decay and completion math. Pure functions — no database, no API calls.
Everything is computed at read time from card review state; nothing is stored.

Frameworks fork: cards reviewed under py-fsrs carry a learned *stability* and
decay on FSRS's power-law forgetting curve, R(t) = (1 + F·t/S)^C with
F = 19/81, C = -0.5 (calibrated so R(S) = 0.9). The scheduler picks due dates
where R hits DUE_RETENTION = 0.75, so "due ⇒ 75%" still holds. Legacy cards
without stability fall back to the original Ebbinghaus exponential
R = e^(−t/(3.476·interval)). Never-reviewed cards are always 0 — reviewing is
the only evidence of knowledge.
"""

import math
from datetime import datetime

DUE_RETENTION = 0.75  # retention of a card exactly at its due date
_STABILITY_SCALE = -1 / math.log(DUE_RETENTION)  # ≈ 3.476 (legacy exponential model)
_FSRS_FACTOR = 19 / 81   # FSRS-4.5+ power curve constants
_FSRS_DECAY = -0.5


def card_retention(interval_days, last_reviewed_at, now=None, stability=None):
    """Retention in [0, 1] for one card. last_reviewed_at is an ISO string or
    None (never reviewed → 0.0). With FSRS stability: power-law curve; without:
    legacy exponential from the SM-2 interval."""
    if not last_reviewed_at:
        return 0.0
    if now is None:
        now = datetime.now()
    elapsed_days = (now - datetime.fromisoformat(last_reviewed_at)).total_seconds() / 86400
    if elapsed_days <= 0:
        return 1.0
    if stability:
        return (1 + _FSRS_FACTOR * elapsed_days / stability) ** _FSRS_DECAY
    legacy_stability = max(interval_days, 1) * _STABILITY_SCALE  # guards interval_days=0
    return math.exp(-elapsed_days / legacy_stability)


def _stability(card):
    # tolerate inputs without a stability field (older callers/tests)
    try:
        return card["stability"]
    except (KeyError, IndexError):
        return None


def topic_mastery(cards, now=None):
    """Mean retention over ALL the topic's cards (unreviewed cards count as 0,
    so partial coverage caps the mean). 0.0 if the topic has no cards."""
    if not cards:
        return 0.0
    total = sum(card_retention(c["interval_days"], c["last_reviewed_at"], now,
                               stability=_stability(c)) for c in cards)
    return total / len(cards)


def _reps(card):
    # tolerate inputs without a repetitions field (older callers/tests)
    try:
        return card["repetitions"]
    except (KeyError, IndexError):
        return 2


def topic_status(cards):
    """Derived, never stored: not_started / in_progress / covered.
    Successive relearning (Rawson & Dunlosky, 2011): a card only counts as
    learned after TWO successive successful recalls (SM-2 repetitions >= 2,
    since a failed recall resets the counter) — so 'covered' means every card
    was recalled correctly twice, not seen once."""
    if not cards:
        return "not_started"
    if all(c["last_reviewed_at"] and _reps(c) >= 2 for c in cards):
        return "covered"
    return "in_progress"


def _topic_kind(topic):
    # tolerate rows/dicts from before the kind column existed
    try:
        return topic["kind"] or "content"
    except (KeyError, IndexError):
        return "content"


def pdf_completion(topics, cards_by_topic, now=None):
    """Completion % (0-100) of a pdf: topic masteries weighted by est_minutes.
    Unstudied topics drag the number down proportionally to their size.
    kind='general' topics (admin/logistics) never get cards, so they are
    excluded — otherwise the pdf could never reach 100%."""
    studyable = [t for t in topics if _topic_kind(t) == "content"] or topics
    if not studyable:
        return 0.0
    weighted_sum = 0.0
    weight_total = 0.0
    for topic in studyable:
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
            "kind": _topic_kind(topic),
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
