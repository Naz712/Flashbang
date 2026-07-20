"""Study statistics computed from the study log. Pure aggregation — no LLM."""

from datetime import datetime, timedelta
from database import get_study_log, get_cards


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
