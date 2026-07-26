"""Annotation (window-box note) checks: CRUD, comment rules, clamping,
cascade. No API needed.
Run: .\\flashbang\\Scripts\\python.exe tests\\check_annotations.py"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import vector_store

# throwaway SQLite AND throwaway Chroma — delete_pdf mirrors into the vector
# store, and temp-db ids collide with real ones
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
database.DB_PATH = tmp.name
vector_store.reset(path=tempfile.mkdtemp(prefix="chroma-check-"))

database.init_db()

course_id = database.create_course("Ann Course")
pdf_id = database.create_pdf(course_id, "ann.pdf", total_pages=3)

# --- round-trip, ordered by page then id; comments trimmed
a1 = database.save_annotation(pdf_id, 2, 0.1, 0.1, 0.2, 0.1, "remember this definition")
a2 = database.save_annotation(pdf_id, 1, 0.5, 0.5, 0.3, 0.2, "  compare with lec04  ")
rows = database.get_annotations(pdf_id)
assert [r["id"] for r in rows] == [a2, a1], "ordered by page then id"
assert rows[0]["comment"] == "compare with lec04", "comment should be trimmed"

# --- a note without a comment is not a note
for bad in ["", "   ", None]:
    try:
        database.save_annotation(pdf_id, 1, 0.1, 0.1, 0.2, 0.2, bad)
        raise AssertionError("empty comment should be rejected")
    except ValueError:
        pass

# --- boxes clamp to the page
a3 = database.save_annotation(pdf_id, 3, 0.95, 0.9, 0.3, 0.4, "edge case")
row = next(r for r in database.get_annotations(pdf_id) if r["id"] == a3)
assert row["x"] + row["w"] <= 1.0 + 1e-9 and row["y"] + row["h"] <= 1.0 + 1e-9

# --- update round-trip; empty update rejected
database.update_annotation(a1, "updated text")
assert next(r for r in database.get_annotations(pdf_id) if r["id"] == a1)["comment"] == "updated text"
try:
    database.update_annotation(a1, " ")
    raise AssertionError("empty update should be rejected")
except ValueError:
    pass

# --- delete one; the rest survive
database.delete_annotation(a2)
assert [r["id"] for r in database.get_annotations(pdf_id)] == [a1, a3]

# --- counts for the reading hub
assert database.get_annotation_counts() == {pdf_id: 2}

# --- pdf delete cascades to its notes
database.delete_pdf(pdf_id)
assert database.get_annotations(pdf_id) == [], "notes must die with their pdf"

os.unlink(tmp.name)
print("check_annotations: ALL PASSED")
