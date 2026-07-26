"""Study statistics computed from the study log. Pure aggregation — no LLM."""

import math
from datetime import datetime, timedelta
from database import get_study_log, get_cards, get_answer_log, get_courses
from mastery import card_retention, DUE_RETENTION
from sm2 import compute_sm2


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

    all_cards = get_cards()

    # ---- knowledge in memory: retrievability-weighted total (FSRS-style)
    held = sum(card_retention(c["interval_days"], c["last_reviewed_at"], now)
               for c in all_cards)
    knowledge = {"held": round(held, 1), "total": len(all_cards),
                 "pct": round(held / len(all_cards) * 100) if all_cards else 0}

    # ---- personal forgetting curve: fit measured recall vs elapsed ratio
    points = [(a["elapsed_ratio"], 1 if a["quality"] >= 3 else 0)
              for a in answers if a["elapsed_ratio"] is not None]
    personal = {"n": len(points), "needed": 10, "k": None,
                "measured_at_due": None, "model_at_due": round(DUE_RETENTION * 100)}
    if len(points) >= 10:
        best_k, best_err = None, float("inf")
        for step in range(1, 151):                      # grid search k in (0, 3]
            k = step * 0.02
            err = sum((math.exp(-k * r) - p) ** 2 for r, p in points)
            if err < best_err:
                best_k, best_err = k, err
        personal["k"] = round(best_k, 3)
        personal["measured_at_due"] = round(math.exp(-best_k) * 100)

    # ---- exam readiness per course with an exam_date set
    exams = {}
    for course in get_courses():
        if not course["exam_date"]:
            continue
        exam_dt = datetime.fromisoformat(course["exam_date"]).replace(hour=9)
        course_cards = [c for c in all_cards if c["course_id"] == course["id"]]
        if exam_dt <= now or not course_cards:
            exams[course["id"]] = {"date": course["exam_date"],
                                   "days_left": max(0, (exam_dt.date() - today).days),
                                   "today": None, "onPlan": None,
                                   "cards": len(course_cards)}
            continue
        # "if you stopped today": decay every card forward to exam day untouched
        stop_today = sum(card_retention(c["interval_days"], c["last_reviewed_at"], exam_dt)
                         for c in course_cards) / len(course_cards)
        # "on schedule": assume each review due before the exam happens (quality 4)
        on_plan = 0.0
        for c in course_cards:
            ease, interval, reps = c["ease_factor"], c["interval_days"], c["repetitions"]
            last, next_review = c["last_reviewed_at"], datetime.fromisoformat(c["next_review"])
            for _ in range(50):                          # safety bound
                if next_review >= exam_dt:
                    break
                last = next_review.isoformat(timespec="seconds")
                ease, interval, reps = compute_sm2(ease, interval, reps, 4)
                next_review = next_review + timedelta(days=interval)
            on_plan += card_retention(interval, last, exam_dt)
        exams[course["id"]] = {"date": course["exam_date"],
                               "days_left": (exam_dt.date() - today).days,
                               "today": round(stop_today * 100),
                               "onPlan": round(on_plan / len(course_cards) * 100),
                               "cards": len(course_cards)}

    # ---- desirable-difficulty sweet spot: last 20 answers vs the ~85% rule
    recent = answers[-20:]
    sweet = {"n": len(recent),
             "rate": round(sum(1 for a in recent if a["quality"] >= 3) / len(recent) * 100)
             if len(recent) >= 5 else None}

    # ---- retrieval fluency: how FAST correct answers come, not just whether
    # they come. Fast+correct signals a strong memory; the fast/slow line is
    # the personal median so typing speed and question length wash out.
    timed = [a for a in answers if a["latency_ms"] is not None
             and (today - datetime.fromisoformat(a["at"]).date()).days < 28]
    fluency = {"n": len(timed), "needed": 6, "split_ms": None, "pass_ms": None,
               "fail_ms": None, "fluent_pct": None,
               "quads": {"fluent": 0, "effortful": 0, "fast_wrong": 0, "slow_wrong": 0}}
    if len(timed) >= 6:
        med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None
        split = med([a["latency_ms"] for a in timed])
        quads = fluency["quads"]
        for a in timed:
            fast, right = a["latency_ms"] <= split, a["quality"] >= 3
            quads["fluent" if fast and right else "effortful" if right
                  else "fast_wrong" if fast else "slow_wrong"] += 1
        fluency.update({
            "split_ms": split,
            "pass_ms": med([a["latency_ms"] for a in timed if a["quality"] >= 3]),
            "fail_ms": med([a["latency_ms"] for a in timed if a["quality"] < 3]),
            "fluent_pct": round(quads["fluent"] / len(timed) * 100)})

    # ---- Brier score from confidence-tagged answers (sure=0.9, unsure=0.5)
    conf_points = [(0.9 if a["confidence"] == "sure" else 0.5, 1 if a["quality"] >= 3 else 0)
                   for a in answers if a["confidence"]]
    brier = {"n": len(conf_points),
             "score": round(sum((p - o) ** 2 for p, o in conf_points) / len(conf_points), 3)
             if len(conf_points) >= 5 else None}

    return {"heatmap": heatmap, "weeks": weeks, "funnel": funnel,
            "retention": retention, "hardest": hardest, "hours": hour_buckets,
            "knowledge": knowledge, "personal": personal, "exams": exams,
            "sweet": sweet, "brier": brier, "fluency": fluency}
