"""Study statistics computed from the study log. Pure aggregation — no LLM."""

from datetime import datetime, timedelta
from database import get_study_log, get_cards, get_answer_log


def compute_stats(now=None):
    if now is None:
        now = datetime.now()
    today = now.date()
    sessions = get_study_log()  # newest first

    study_days = sorted({datetime.fromisoformat(s["started_at"]).date()
                         for s in sessions})

    # current streak: consecutive days ending today or yesterday (today still counts
    # as alive if you haven't studied yet)
    current_streak = 0
    if study_days:
        day = today if today in study_days else today - timedelta(days=1)
        while day in study_days:
            current_streak += 1
            day -= timedelta(days=1)

    # longest streak
    longest_streak = 0
    run = 0
    prev = None
    for day in study_days:
        run = run + 1 if prev is not None and day - prev == timedelta(days=1) else 1
        longest_streak = max(longest_streak, run)
        prev = day

    # this week (last 7 days incl. today)
    week_start = today - timedelta(days=6)
    week_sessions = [s for s in sessions
                     if datetime.fromisoformat(s["started_at"]).date() >= week_start]
    week_minutes = sum(s["minutes"] or 0 for s in week_sessions)
    week_cards = sum(s["cards_reviewed"] for s in week_sessions)

    # per-day series for the last 14 days (charting)
    daily = []
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        day_sessions = [s for s in sessions
                        if datetime.fromisoformat(s["started_at"]).date() == day]
        daily.append({
            "date": day.isoformat(),
            "minutes": round(sum(s["minutes"] or 0 for s in day_sessions), 1),
            "cards": sum(s["cards_reviewed"] for s in day_sessions),
        })

    all_cards = get_cards()
    return {
        "current_streak_days": current_streak,
        "longest_streak_days": longest_streak,
        "week_minutes": round(week_minutes, 1),
        "week_cards_reviewed": week_cards,
        "week_sessions": len(week_sessions),
        "total_sessions": len(sessions),
        "total_cards": len(all_cards),
        "cards_reviewed_ever": sum(1 for c in all_cards if c["last_reviewed_at"]),
        "daily_last_14": daily,
    }


def compute_metrics(now=None, weeks=26):
    """Deeper study metrics for the Progress screen. All derived from data
    already collected — sessions, cards, and the graded-answer log."""
    if now is None:
        now = datetime.now()
    today = now.date()

    # ---- heatmap: daily minutes, last `weeks` weeks, aligned to Monday
    sessions = get_study_log()
    minutes_by_day = {}
    for s in sessions:
        day = datetime.fromisoformat(s["started_at"]).date()
        minutes_by_day[day] = minutes_by_day.get(day, 0) + (s["minutes"] or 0)
    this_monday = today - timedelta(days=today.weekday())
    start_monday = this_monday - timedelta(weeks=weeks - 1)
    heatmap = []
    for w in range(weeks):
        for d in range(7):
            day = start_monday + timedelta(weeks=w, days=d)
            heatmap.append({
                "date": day.isoformat(),
                "minutes": round(minutes_by_day.get(day, 0), 1),
                "future": day > today,
            })

    # ---- maturity funnel (Anki-style): interval says how stable a memory is
    funnel = {"new": 0, "learning": 0, "young": 0, "mature": 0}
    for c in get_cards():
        if not c["last_reviewed_at"]:
            funnel["new"] += 1
        elif c["interval_days"] < 7:
            funnel["learning"] += 1
        elif c["interval_days"] < 21:
            funnel["young"] += 1
        else:
            funnel["mature"] += 1

    # ---- retention trend: weekly recall rate from ALL graded answers
    answers = get_answer_log(days=weeks * 7)
    week_buckets = {}
    for a in answers:
        age = (today - datetime.fromisoformat(a["at"]).date()).days // 7
        if age >= 8:
            continue
        bucket = week_buckets.setdefault(age, [0, 0])
        bucket[0] += 1
        if a["quality"] >= 3:
            bucket[1] += 1
    retention = []
    for age in range(7, -1, -1):
        n, passed = week_buckets.get(age, [0, 0])
        retention.append({"label": "now" if age == 0 else f"-{age}w",
                          "n": n, "rate": round(passed / n * 100) if n else None})

    # ---- hardest cards: most failed recalls (≥2 attempts to qualify)
    per_card = {}
    for a in answers:
        if a["card_id"] is None:
            continue
        entry = per_card.setdefault(a["card_id"], {"n": 0, "fails": 0,
                                                   "question": a["question"],
                                                   "topic": a["topic_title"]})
        entry["n"] += 1
        if a["quality"] < 3:
            entry["fails"] += 1
    hardest = sorted(
        ({"card_id": cid, **e, "fail_rate": round(e["fails"] / e["n"] * 100)}
         for cid, e in per_card.items() if e["n"] >= 2 and e["fails"] > 0),
        key=lambda e: (-e["fails"], -e["fail_rate"]))[:5]

    # ---- best study hours: recall rate by time-of-day bucket (n ≥ 5 to show)
    HOURS = [("morning", 5, 12), ("afternoon", 12, 17), ("evening", 17, 22), ("night", 22, 29)]
    hour_buckets = []
    for label, start, end in HOURS:
        hits = [a for a in answers
                if start <= (datetime.fromisoformat(a["at"]).hour + (24 if datetime.fromisoformat(a["at"]).hour < 5 else 0)) < end]
        n = len(hits)
        passed = sum(1 for a in hits if a["quality"] >= 3)
        hour_buckets.append({"label": label, "n": n,
                             "rate": round(passed / n * 100) if n >= 5 else None})

    return {"heatmap": heatmap, "weeks": weeks, "funnel": funnel,
            "retention": retention, "hardest": hardest, "hours": hour_buckets}
