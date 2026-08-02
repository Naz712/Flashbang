r"""Topic primers: storage, caching and replacement. Offline — the generator
itself needs the API key, so this exercises everything around it.

Run: .\flashbang\Scripts\python.exe tests\check_primer.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db
import vector_store

tmp = tempfile.mkdtemp(prefix="fb_primer_")
db.DB_PATH = os.path.join(tmp, "test.db")
# temp-db ids collide with real ids, and delete_* mirrors into the live Chroma
# store — isolate it or a test wipes real embeddings
vector_store.reset(path=os.path.join(tmp, "chroma"))
db.init_db()

course_id = db.create_course("Test course")
pdf_id = db.create_pdf(course_id, "primer.pdf", total_pages=4)

db.save_topics(pdf_id, [{"title": "Recursion", "page_start": 1, "page_end": 4,
                         "est_minutes": 20, "kind": "content"}])
topic_id = db.get_topics(pdf_id=pdf_id)[0]["id"]

# ---- empty to start
assert db.get_primer(topic_id) is None, "a fresh topic must have no primer"
assert db.topics_with_primers() == set(), "no primers yet"

# ---- save and read back, JSON columns parsed
primer = {
    "gist": "Recursion is a function calling itself on a smaller piece.",
    "analogy": "Like standing between two mirrors.",
    "mapping": [{"this": "each reflection", "is": "one call on the stack"},
                {"this": "the last visible one", "is": "the base case"}],
    "breaks": "Mirrors go on forever; a function without a base case crashes.",
    "ideas": ["base case", "call stack", "recurrence"],
    "prereq": "You should know what a function call is.",
}
db.save_primer(topic_id, primer, model="test-model")
got = db.get_primer(topic_id)
assert got is not None, "primer should exist after save"
assert got["gist"] == primer["gist"]
assert isinstance(got["mapping"], list) and len(got["mapping"]) == 2, "mapping comes back parsed"
assert got["mapping"][0]["is"] == "one call on the stack"
assert isinstance(got["ideas"], list) and got["ideas"][0] == "base case", "ideas come back parsed"
assert got["breaks"], "the analogy's limits are stored, not dropped"
assert got["model"] == "test-model" and got["created_at"], "provenance recorded"
assert db.topics_with_primers() == {topic_id}

# ---- regenerating REPLACES rather than accumulating
primer2 = dict(primer, gist="A second take.", ideas=["base case"])
db.save_primer(topic_id, primer2, model="test-model-2")
conn = db.get_conn()
n = conn.execute("SELECT COUNT(*) AS n FROM topic_primers WHERE topic_id=?", (topic_id,)).fetchone()["n"]
conn.close()
assert n == 1, f"regenerate must replace, not duplicate (found {n} rows)"
assert db.get_primer(topic_id)["gist"] == "A second take."
assert db.get_primer(topic_id)["model"] == "test-model-2"

# ---- explicit delete
db.delete_primer(topic_id)
assert db.get_primer(topic_id) is None, "delete removes the primer"

# ---- a deleted topic takes its primer with it (ON DELETE CASCADE)
db.save_primer(topic_id, primer)
assert db.get_primer(topic_id) is not None
db.delete_topic(topic_id)
assert db.get_primer(topic_id) is None, "deleting a topic must not orphan its primer"

print("check_primer: ALL PASSED")
