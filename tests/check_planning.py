"""Planning + stats checks. No API needed.
Run: .\\flashbang\\Scripts\\python.exe tests\\check_planning.py"""

import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
database.DB_PATH = tmp.name
database.init_db()

import planning
import stats as stats_module
from database import get_conn

now = datetime.now()
course_id = database.create_course("Plan Course")
pdf_id = database.create_pdf(course_id, "plan.pdf", total_pages=12)
database.save_pdf_pages(pdf_id, [{"page_number": 1, "text": "x", "extractor": "pypdf"}])
topic_ids = database.save_topics(pdf_id, [
    {"title": "Due Topic",       "summary": "", "page_start": 1, "page_end": 4,  "est_minutes": 40},
    {"title": "Unstarted Topic", "summary": "", "page_start": 5, "page_end": 8,  "est_minutes": 90},
    {"title": "New Cards Topic", "summary": "", "page_start": 9, "page_end": 12, "est_minutes": 30},
])

# topic 0: 5 cards overdue (reviewed 10 days ago, 3-day interval)
overdue_ids = [database.insert_card(topic_ids[0], "Q?", "A.") for _ in range(5)]
reviewed = (now - timedelta(days=10)).isoformat(timespec="seconds")
due = (now - timedelta(days=7)).isoformat(timespec="seconds")
conn = get_conn()
for card_id in overdue_ids:
    conn.execute("UPDATE cards SET last_reviewed_at=?, next_review=?, interval_days=3 WHERE id=?",
                 (reviewed, due, card_id))
conn.commit()
conn.close()
# topic 1: no cards (first study, 90 min). topic 2: 4 cards never reviewed.
for _ in range(4):
    database.insert_card(topic_ids[2], "Q?", "A.")

proposal = planning.propose_plan(days=3, minutes_per_day=45, course_id=course_id)
entries = proposal["entries"]
assert entries, "no plan proposed"

# budget respected per day
by_date = {}
for e in entries:
    by_date.setdefault(e["plan_date"], []).append(e)
for date_str, day_entries in by_date.items():
    total = sum(e["minutes"] for e in day_entries)
    assert total <= 45, f"{date_str} over budget: {total}"

# most urgent item (due topic) scheduled first, on day 1
today = now.date().isoformat()
first_day = by_date.get(today, [])
assert any(e["topic_id"] == topic_ids[0] for e in first_day), "due topic not on day 1"

# the 90-min first-study is split across days or partially unscheduled — never silently dropped
scheduled_90 = sum(e["minutes"] for e in entries if e["topic_id"] == topic_ids[1])
unscheduled_90 = sum(u["minutes"] for u in proposal["unscheduled"]
                     if u["title"] == "Unstarted Topic")
assert scheduled_90 + unscheduled_90 == 90, \
    f"first-study minutes lost: {scheduled_90} + {unscheduled_90} != 90"
# every scheduled chunk respects the minimum size
assert all(e["minutes"] >= planning.MIN_CHUNK for e in entries)

# save + derived status
saved = database.save_study_plan(entries)
assert saved == len(entries)
plan = database.get_study_plan()
assert all(p["status"] == "planned" for p in plan), "future entries should be 'planned'"

# a review session today on the due topic flips today's entry to done
session_id = database.start_session("review", course_id=course_id)
conn = get_conn()
conn.execute("INSERT OR IGNORE INTO session_topics (session_id, topic_id) VALUES (?, ?)",
             (session_id, topic_ids[0]))
conn.commit()
conn.close()
database.end_session(session_id, cards_reviewed=5)
plan = database.get_study_plan()
today_due = [p for p in plan if p["plan_date"] == today and p["topic_id"] == topic_ids[0]]
assert today_due and today_due[0]["status"] == "done", "session should mark plan entry done"

# a plan entry in the past with no session derives 'missed'
database.save_study_plan([{"topic_id": topic_ids[1],
                           "plan_date": (now - timedelta(days=2)).date().isoformat(),
                           "minutes": 30, "reason": "test"}], replace_future=False)
plan = database.get_study_plan()
missed = [p for p in plan if p["status"] == "missed"]
assert len(missed) == 1

# re-plan replaces future entries, keeps past ones
database.save_study_plan(entries[:1])
plan = database.get_study_plan()
future = [p for p in plan if p["plan_date"] >= today]
assert len(future) == 1, f"replan should leave 1 future entry, got {len(future)}"
assert any(p["plan_date"] < today for p in plan), "past history should survive replan"

# --- stats
s = stats_module.compute_stats()
assert s["current_streak_days"] >= 1, "today's session should start a streak"
assert s["week_cards_reviewed"] == 5
assert s["total_cards"] == 9
assert len(s["daily_last_14"]) == 14
assert s["daily_last_14"][-1]["date"] == today

# --- deeper metrics
database.log_answer(5, "sure", overdue_ids[0])
database.log_answer(2, None, overdue_ids[1])
m = stats_module.compute_metrics()
assert len(m["heatmap"]) == 26 * 7
assert sum(m["funnel"].values()) == 9, f"funnel misses cards: {m['funnel']}"
assert m["funnel"]["new"] == 4 and m["funnel"]["learning"] == 5  # 5 backdated at 3d interval
this_week = m["retention"][-1]
assert this_week["n"] == 2 and this_week["rate"] == 50, f"retention wrong: {this_week}"
assert all(h["rate"] is None for h in m["hours"]), "hour buckets need 5+ answers to judge"
assert m["hardest"] == [] or m["hardest"][0]["fails"] >= 1  # single-fail cards need n>=2

# --- knowledge in memory: 5 reviewed-overdue cards hold partial retention, 4 new = 0
assert m["knowledge"]["total"] == 9
assert 0 < m["knowledge"]["held"] < 5, f"held out of range: {m['knowledge']}"
# personal curve needs 10 timed recalls before it fits
assert m["personal"]["k"] is None and m["personal"]["n"] == 0
# sweet spot / brier respect their minimum-n gates (2 answers so far)
assert m["sweet"]["rate"] is None and m["brier"]["score"] is None

# --- exam readiness: on-schedule projection must beat stop-today
exam_day = (now + timedelta(days=21)).date().isoformat()
database.set_exam_date(course_id, exam_day)
m = stats_module.compute_metrics()
exam = m["exams"][course_id]
assert exam["days_left"] == 21 and exam["cards"] == 9
assert exam["onPlan"] > exam["today"], f"plan should beat stopping: {exam}"
assert 0 <= exam["today"] <= 100 and 0 <= exam["onPlan"] <= 100

os.unlink(tmp.name)
print("check_planning: ALL PASSED")
