r"""Tutorials: the practice pool. Storage, topic tagging, flags, answer pages
and the filters the UI relies on. Offline — the splitter itself needs the API
key, so this exercises everything around it.

Run: .\flashbang\Scripts\python.exe tests\check_tutorials.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db
import vector_store

tmp = tempfile.mkdtemp(prefix="fb_tut_")
db.DB_PATH = os.path.join(tmp, "test.db")
# temp-db ids collide with real ids, and delete_* mirrors into the live Chroma
# store — isolate it or a test wipes real embeddings
vector_store.reset(path=os.path.join(tmp, "chroma"))
db.init_db()

course_id = db.create_course("CS2030")
notes_pdf = db.create_pdf(course_id, "lec01.pdf", total_pages=10)
db.save_topics(notes_pdf, [
    {"title": "Recursion", "page_start": 1, "page_end": 5, "est_minutes": 20, "kind": "content"},
    {"title": "Streams", "page_start": 6, "page_end": 10, "est_minutes": 20, "kind": "content"},
])
topics = db.get_topics(pdf_id=notes_pdf)
recursion = [t for t in topics if t["title"] == "Recursion"][0]["id"]
streams = [t for t in topics if t["title"] == "Streams"][0]["id"]

# ---- kind keeps tutorials OUT of the notes list
tut_pdf = db.create_pdf(course_id, "tut03.pdf", total_pages=3, kind="tutorial")
notes = db.get_pdfs(course_id=course_id)
assert [p["id"] for p in notes] == [notes_pdf], \
    "a tutorial paper must not appear in the documents list"
assert len(db.get_pdfs(course_id=course_id, kind="tutorial")) == 1
assert len(db.get_pdfs(course_id=course_id, kind=None)) == 2, "kind=None means every pdf"

# ---- a tutorial and its questions, one row per LEAF part
tid = db.create_tutorial(course_id, "Tutorial 3", tut_pdf)
qs = [
    {"label": "1", "grp": "1", "text": "Define a recurrence.", "page": 1, "topic_ids": [recursion]},
    {"label": "2(a)", "grp": "2", "text": "Write a recursive factorial.", "page": 1, "topic_ids": [recursion]},
    {"label": "2(b)", "grp": "2", "text": "Give its base case.", "page": 2, "topic_ids": [recursion]},
    {"label": "3", "grp": "3", "text": "Map a stream to squares.", "page": 2, "topic_ids": [streams]},
]
ids = db.save_tutorial_questions(tid, qs)
assert len(ids) == 4, "each leaf part is its own question"
for qid, q in zip(ids, qs):
    db.set_question_topics(qid, q["topic_ids"])

got = db.get_tutorial_questions(tutorial_id=tid)
assert [q["label"] for q in got] == ["1", "2(a)", "2(b)", "3"], "order preserved"
assert got[1]["grp"] == "2" and got[2]["grp"] == "2", "parts share a group"
assert got[0]["topics"][0]["title"] == "Recursion", "topics come back joined"
assert all(q["flagged"] == 0 for q in got), "nothing starts flagged"

# ---- flags
db.flag_question(ids[2], True, "never got the base case")
flagged = db.get_tutorial_questions(tutorial_id=tid, flagged_only=True)
assert len(flagged) == 1 and flagged[0]["label"] == "2(b)"
assert flagged[0]["flag_note"] == "never got the base case"

# ---- FLAGS SURVIVE A RE-SPLIT. A flag is the student's own work; losing it
# because the split was re-run would be the worst kind of data loss.
ids2 = db.save_tutorial_questions(tid, qs)
again = db.get_tutorial_questions(tutorial_id=tid)
assert len(again) == 4, "re-splitting replaces rather than accumulating"
kept = [q for q in again if q["label"] == "2(b)"][0]
assert kept["flagged"] == 1, "a flag must survive re-splitting"
assert kept["flag_note"] == "never got the base case", "and so must its note"
for qid, q in zip(ids2, qs):
    db.set_question_topics(qid, q["topic_ids"])

# ---- filter by topic: the "I'm weak on X, show me questions on X" path
rec = db.get_tutorial_questions(course_id=course_id, topic_id=recursion)
assert [q["label"] for q in rec] == ["1", "2(a)", "2(b)"], f"got {[q['label'] for q in rec]}"
assert [q["label"] for q in db.get_tutorial_questions(course_id=course_id, topic_id=streams)] == ["3"]

# ---- answers arrive later, and only a PAGE MAP is stored
assert all(q["answer_page"] is None for q in db.get_tutorial_questions(tutorial_id=tid)), \
    "no answers until the answer paper is added"
ans_pdf = db.create_pdf(course_id, "tut03_ans.pdf", total_pages=4, kind="answers")
db.set_answer_pdf(tid, ans_pdf)
by_id = {q["id"]: q["label"] for q in db.get_tutorial_questions(tutorial_id=tid)}
db.set_answer_pages({qid: 2 for qid, label in by_id.items() if label.startswith("2")})
after = db.get_tutorial_questions(tutorial_id=tid)
assert [q["answer_page"] for q in after] == [None, 2, 2, None], \
    "only the located answers get a page; the rest stay honest about not knowing"
assert all(q["answer_pdf_id"] == ans_pdf for q in after), "questions know their answer paper"
assert db.get_pdfs(course_id=course_id) and \
    [p["id"] for p in db.get_pdfs(course_id=course_id)] == [notes_pdf], \
    "the answer paper must not appear in the documents list either"

# ---- tutorial listing carries the counts the UI shows
listed = db.get_tutorials(course_id)
assert len(listed) == 1
assert listed[0]["n_questions"] == 4 and listed[0]["n_flagged"] == 1
assert listed[0]["answer_filename"] == "tut03_ans.pdf"

# ---- deleting the tutorial takes its questions and tags with it
db.delete_tutorial(tid)
assert db.get_tutorial_questions(tutorial_id=tid) == [], "questions cascade"
conn = db.get_conn()
left = conn.execute("SELECT COUNT(*) AS n FROM tutorial_question_topics").fetchone()["n"]
conn.close()
assert left == 0, f"topic tags must cascade too ({left} left)"

# ---- deleting a TOPIC drops its tags but never the questions
tid2 = db.create_tutorial(course_id, "Tutorial 4", tut_pdf)
ids3 = db.save_tutorial_questions(tid2, [{"label": "1", "grp": "1", "text": "q", "page": 1}])
db.set_question_topics(ids3[0], [streams])
db.delete_topic(streams)
survivors = db.get_tutorial_questions(tutorial_id=tid2)
assert len(survivors) == 1, "deleting a topic must not delete the question"
assert survivors[0]["topics"] == [], "but its tag goes"

print("check_tutorials: ALL PASSED")
