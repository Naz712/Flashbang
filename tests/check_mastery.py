"""Decay/completion math checks. Pure — no API, no DB.
Run: .\\flashbang\\Scripts\\python.exe tests\\check_mastery.py"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mastery import (card_retention, topic_mastery, topic_status,
                     pdf_completion, DUE_RETENTION)

now = datetime(2026, 7, 16, 12, 0, 0)


def iso(days_ago):
    return (now - timedelta(days=days_ago)).isoformat(timespec="seconds")


# R(0) = 1
assert abs(card_retention(10, iso(0), now) - 1.0) < 1e-9

# card exactly at its due date -> DUE_RETENTION
r_due = card_retention(10, iso(10), now)
assert abs(r_due - DUE_RETENTION) < 1e-6, f"expected {DUE_RETENTION}, got {r_due}"

# same for a 1-day interval
assert abs(card_retention(1, iso(1), now) - DUE_RETENTION) < 1e-6

# monotone decreasing
r = [card_retention(10, iso(d), now) for d in (0, 5, 10, 20, 40)]
assert all(a > b for a, b in zip(r, r[1:])), f"not monotone: {r}"

# one full interval overdue ~= DUE_RETENTION^2
assert abs(card_retention(10, iso(20), now) - DUE_RETENTION ** 2) < 1e-6

# never-reviewed card = 0; interval_days=0 must not divide by zero
assert card_retention(10, None, now) == 0.0
assert 0 < card_retention(0, iso(0.5 / 24), now) <= 1.0

# --- FSRS power-law branch (frameworks fork): stability drives the curve
S = 12.0
assert abs(card_retention(0, iso(0), now, stability=S) - 1.0) < 1e-9
# FSRS calibration: retention at t = S is exactly 0.9
assert abs(card_retention(0, iso(S), now, stability=S) - 0.9) < 1e-6
# scheduler places the due date at t = S·63/19, where the curve hits 0.75
t_due = S * 63 / 19
assert abs(card_retention(0, iso(t_due), now, stability=S) - 0.75) < 1e-6
# monotone decreasing on the power curve too
fs = [card_retention(0, iso(d), now, stability=S) for d in (0, 6, 12, 30, 90)]
assert all(a > b for a, b in zip(fs, fs[1:])), f"FSRS curve not monotone: {fs}"
# power-law forgets SLOWER in the far tail than the old exponential (fat tail)
assert card_retention(0, iso(120), now, stability=S) > card_retention(3, iso(120), now)
# topic_mastery picks up stability from card dicts when present
assert abs(topic_mastery([{"interval_days": 0, "last_reviewed_at": iso(S),
                           "stability": S}], now) - 0.9) < 1e-6

# topic mastery: mean over ALL cards, unreviewed count as 0
cards = [
    {"interval_days": 10, "last_reviewed_at": iso(0)},   # 1.0
    {"interval_days": 10, "last_reviewed_at": None},     # 0.0
]
assert abs(topic_mastery(cards, now) - 0.5) < 1e-9
assert topic_mastery([], now) == 0.0

# derived status
assert topic_status([]) == "not_started"
assert topic_status(cards) == "in_progress"
assert topic_status([cards[0]]) == "covered"  # no repetitions field → tolerated

# successive relearning: one successful recall isn't 'covered' — two are
one_recall = {"interval_days": 1, "last_reviewed_at": iso(0), "repetitions": 1}
two_recalls = {"interval_days": 6, "last_reviewed_at": iso(0), "repetitions": 2}
assert topic_status([one_recall]) == "in_progress"
assert topic_status([two_recalls]) == "covered"
assert topic_status([one_recall, two_recalls]) == "in_progress"

# pdf completion: est_minutes-weighted
topics = [
    {"id": 1, "est_minutes": 30},  # mastery 1.0
    {"id": 2, "est_minutes": 90},  # mastery 0.0 (no cards)
]
cards_by_topic = {1: [{"interval_days": 10, "last_reviewed_at": iso(0)}]}
pct = pdf_completion(topics, cards_by_topic, now)
assert abs(pct - 25.0) < 1e-6, f"expected 25.0, got {pct}"  # 30*1 / 120

# empty pdf
assert pdf_completion([], {}, now) == 0.0

# zero-minute topics fall back to weight 1
topics_zero = [{"id": 1, "est_minutes": 0}, {"id": 2, "est_minutes": 0}]
pct = pdf_completion(topics_zero, cards_by_topic, now)
assert abs(pct - 50.0) < 1e-6

# kind='general' topics are excluded from completion (they never get cards)
topics_kinds = [
    {"id": 1, "est_minutes": 30, "kind": "content"},   # mastery 1.0
    {"id": 2, "est_minutes": 90, "kind": "general"},   # admin pages — ignored
]
pct = pdf_completion(topics_kinds, cards_by_topic, now)
assert abs(pct - 100.0) < 1e-6, f"general topic should not drag completion, got {pct}"
# an all-general pdf falls back to counting everything rather than dividing by zero
assert pdf_completion([{"id": 2, "est_minutes": 10, "kind": "general"}], {}, now) == 0.0

print("check_mastery: ALL PASSED")
