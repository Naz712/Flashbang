"""Schema checks: FK enforcement, cascades, timestamps. No API needed.
Run: .\\flashbang\\Scripts\\python.exe tests\\check_db.py"""

import os
import sys
import sqlite3
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database

# point the module at a throwaway file
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
database.DB_PATH = tmp.name

database.init_db()

# --- basic entity chain
course_id = database.create_course("Test Course")
pdf_id = database.create_pdf(course_id, "test.pdf", total_pages=10)
database.save_pdf_pages(pdf_id, [
    {"page_number": 1, "text": "page one text", "extractor": "pypdf"},
    {"page_number": 2, "text": "page two text", "extractor": "vision"},
])
topic_ids = database.save_topics(pdf_id, [
    {"title": "Topic A", "summary": "s", "page_start": 1, "page_end": 5, "est_minutes": 30},
    {"title": "Topic B", "summary": "s", "page_start": 6, "page_end": 10, "est_minutes": 20},
])
assert len(topic_ids) == 2

pdf = database.get_pdf(pdf_id)
assert pdf["est_total_minutes"] == 50, f"expected 50, got {pdf['est_total_minutes']}"
assert pdf["status"] == "ready"

card_id = database.insert_card(topic_ids[0], "Q?", "A.")
card = database.get_cards(topic_id=topic_ids[0])[0]
assert card["pdf_id"] == pdf_id and card["course_id"] == course_id, "FKs not derived from topic"
assert card["last_reviewed_at"] is None

# --- timestamps are full ISO and round-trip
assert "T" in card["next_review"], f"next_review not full timestamp: {card['next_review']}"
datetime.fromisoformat(card["created_at"])

# --- review stamps last_reviewed_at and grows interval
result = database.review_card(card_id, 5)
assert result["new_interval"] >= 1 and result["old_interval"] == 0
card = database.get_cards(topic_id=topic_ids[0])[0]
assert card["last_reviewed_at"] is not None

# --- undo restores the pre-review state, one level deep
prev = database.undo_review(card_id)
card = database.get_cards(topic_id=topic_ids[0])[0]
assert card["last_reviewed_at"] is None and card["interval_days"] == 0
try:
    database.undo_review(card_id)
    raise AssertionError("second undo should have raised")
except ValueError:
    pass
database.review_card(card_id, 5)  # re-review so later session checks still hold

# --- FK enforcement: orphan insert must fail
try:
    database.insert_card(99999, "Q?", "A.")
    raise AssertionError("insert_card with bogus topic should have raised")
except ValueError:
    pass

conn = database.get_conn()
try:
    conn.execute("INSERT INTO cards (topic_id, pdf_id, course_id, question, answer, next_review, created_at) "
                 "VALUES (99999, 99999, 99999, 'q', 'a', '2026-01-01T00:00:00', '2026-01-01T00:00:00')")
    raise AssertionError("raw orphan insert should have raised (FKs not enforced?)")
except sqlite3.IntegrityError:
    pass
finally:
    conn.close()

# --- study session lifecycle: derived count + topic links
session_id = database.start_session("review", course_id=course_id)
database.review_card(card_id, 4)
result = database.end_session(session_id)
assert result["cards_reviewed"] == 1, f"expected 1 derived review, got {result['cards_reviewed']}"
log = database.get_study_log()
assert len(log) == 1 and log[0]["topic_titles"] == "Topic A"
assert log[0]["minutes"] is not None

# --- upcoming reviews sees the card
upcoming = database.get_upcoming_reviews(days=30)
assert len(upcoming) == 1 and upcoming[0]["topic_id"] == topic_ids[0]

# --- cascade: deleting the course wipes everything, log survives with NULL refs
database.delete_course(course_id)
assert database.get_cards() == []
assert database.get_topics() == []
assert database.get_pdfs() == []
log = database.get_study_log()
assert len(log) == 1 and log[0]["course_id"] is None, "study log should survive course deletion"

# --- answer log + calibration + topic accuracy (85% rule inputs)
course2 = database.create_course("Cal Course")
pdf2 = database.create_pdf(course2, "cal.pdf", total_pages=2)
database.save_pdf_pages(pdf2, [{"page_number": 1, "text": "x", "extractor": "pypdf"}])
tid = database.save_topics(pdf2, [
    {"title": "Cal Topic", "summary": "", "page_start": 1, "page_end": 2, "est_minutes": 10}])[0]
cid = database.insert_card(tid, "Q?", "A.")
for quality, conf in [(5, "sure"), (4, "sure"), (2, "unsure"), (4, "unsure"), (5, None), (3, None)]:
    aid = database.log_answer(quality, conf)
    database.attach_card_to_answer(aid, cid)

cal = database.get_calibration(28)
this_week = cal[-1]
assert this_week["sure_n"] == 2 and this_week["sure_rate"] == 100
assert this_week["unsure_n"] == 2 and this_week["unsure_rate"] == 50

acc = database.get_topic_accuracy(min_answers=6)
assert acc == {tid: 83}, f"expected {{{tid}: 83}}, got {acc}"  # 5 of 6 passed
assert database.get_topic_accuracy(min_answers=7) == {}, "min_answers threshold ignored"

# --- topic kind flag: persists, defaults to content, rejects junk values
pdf_k = database.create_pdf(course2, "kinds.pdf", total_pages=3)
kind_ids = database.save_topics(pdf_k, [
    {"title": "Real Topic", "summary": "", "page_start": 1, "page_end": 2, "est_minutes": 10, "kind": "content"},
    {"title": "Course Admin", "summary": "", "page_start": 3, "page_end": 3, "est_minutes": 2, "kind": "general"},
    {"title": "No Kind Given", "summary": "", "page_start": 3, "page_end": 3, "est_minutes": 2},
])
kinds = {t["title"]: t["kind"] for t in database.get_topics(pdf_id=pdf_k)}
assert kinds == {"Real Topic": "content", "Course Admin": "general", "No Kind Given": "content"}, kinds
database.delete_pdf(pdf_k)

# --- delete_pdf cascade: pdf + topics + cards gone, course and log survive
pdf3 = database.create_pdf(course2, "doomed.pdf", total_pages=1)
tid3 = database.save_topics(pdf3, [
    {"title": "Doomed Topic", "summary": "", "page_start": 1, "page_end": 1, "est_minutes": 5}])[0]
database.insert_card(tid3, "Q?", "A.")
database.delete_pdf(pdf3)
assert all(p["id"] != pdf3 for p in database.get_pdfs()), "pdf row should be gone"
assert all(t["pdf_id"] != pdf3 for t in database.get_topics()), "topics should cascade"
assert all(c["pdf_id"] != pdf3 for c in database.get_cards()), "cards should cascade"
assert any(c["id"] == course2 for c in database.get_courses()), "course must survive pdf delete"

# --- response latency round-trip (retrieval fluency input)
aid = database.log_answer(4, "sure", latency_ms=8250)
timed = [a for a in database.get_answer_log(days=1) if a["latency_ms"] is not None]
assert len(timed) == 1 and timed[0]["latency_ms"] == 8250, "latency_ms should round-trip"
assert all(a["latency_ms"] is None for a in database.get_answer_log(days=1)
           if a["quality"] == 2), "untimed answers must stay NULL"

# --- session accuracy column
sid = database.start_session("review", course_id=course2)
database.end_session(sid, cards_reviewed=6)
database.set_session_accuracy(sid, 83)
row = next(r for r in database.get_study_log() if r["id"] == sid)
assert row["accuracy"] == 83

os.unlink(tmp.name)
print("check_db: ALL PASSED")
