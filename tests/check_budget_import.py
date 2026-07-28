"""Daily-budget + card-import checks: settings, per-card pace, backlog
spreading, deterministic flashcard parsing. No API needed (the parser's AI
fallback is deliberately not exercised here).
Run: .\\flashbang\\Scripts\\python.exe tests\\check_budget_import.py"""

import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import vector_store

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
database.DB_PATH = tmp.name
vector_store.reset(path=tempfile.mkdtemp(prefix="chroma-check-"))

database.init_db()

# --- settings round-trip
assert database.get_setting("daily_minutes") is None
assert database.get_setting("daily_minutes", "0") == "0"
database.set_setting("daily_minutes", 25)
assert database.get_setting("daily_minutes") == "25"
database.set_setting("daily_minutes", 45)          # upsert, not duplicate
assert database.get_setting("daily_minutes") == "45"

# --- seconds_per_card: 84s fallback until 6 timed answers, then measured
import stats
assert stats.seconds_per_card() == 84
for ms in (4000, 6000, 8000, 10000, 12000, 60000):
    database.log_answer(4, latency_ms=ms)
# median of sorted latencies (len 6 -> index 3 = 10000ms) + 25s overhead
assert stats.seconds_per_card() == 35, stats.seconds_per_card()

# --- spread_backlog: first per_day stay due, rest chunked onto later days
course = database.create_course("Budget Course")
pdf = database.create_pdf(course, "b.pdf", total_pages=5)
tid = database.save_topics(pdf, [
    {"title": "T", "summary": "", "page_start": 1, "page_end": 5, "est_minutes": 10}])[0]
card_ids = [database.insert_card(tid, f"Q{i}?", "A.") for i in range(5)]

conn = database.get_conn()
for i, cid in enumerate(card_ids):   # stagger overdueness: Q0 most overdue
    past = (datetime.now() - timedelta(days=5 - i)).isoformat(timespec="seconds")
    conn.execute("UPDATE cards SET next_review = ?, interval_days = 3 WHERE id = ?", (past, cid))
conn.commit()
conn.close()

result = database.spread_backlog(per_day=2)
assert result == {"moved": 3, "days_used": 2}, result

today = datetime.now().date()
conn = database.get_conn()
rows = {r["id"]: r for r in conn.execute("SELECT id, next_review, interval_days FROM cards")}
conn.close()
due_day = lambda cid: datetime.fromisoformat(rows[cid]["next_review"]).date()
assert due_day(card_ids[0]) < today and due_day(card_ids[1]) < today, "most overdue stay due"
assert due_day(card_ids[2]) == today + timedelta(days=1)
assert due_day(card_ids[3]) == today + timedelta(days=1)
assert due_day(card_ids[4]) == today + timedelta(days=2)
assert all(r["interval_days"] == 3 for r in rows.values()), "scheduling state must not change"
assert len(database.get_due_cards()) == 2, "only the kept chunk is still due"

# spreading when everything fits is a no-op
assert database.spread_backlog(per_day=50) == {"moved": 0, "days_used": 0}

# --- deterministic flashcard parsing (no LLM call on these paths)
from generation import parse_flashcards

cards, src = parse_flashcards("What is OOP?\tA programming paradigm.\nWhat is HOF?\tA function taking functions.")
assert src == "parsed" and len(cards) == 2 and cards[1]["answer"] == "A function taking functions."

cards, src = parse_flashcards("front one :: back one\nfront two :: back two")
assert src == "parsed" and len(cards) == 2

cards, src = parse_flashcards("""Q: What does self refer to?
A: The instance the method was
   called on.
Question: Why use packages?
Answer: Namespacing and reuse.""")
assert src == "parsed" and len(cards) == 2, cards
assert cards[0]["answer"] == "The instance the method was called on."

cards, src = parse_flashcards("")
assert cards == [] and src == "parsed"

os.unlink(tmp.name)
print("check_budget_import: ALL PASSED")
