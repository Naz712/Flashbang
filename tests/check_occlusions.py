"""Blackout-tool checks: CRUD, clamping, cascade. No API needed.
Run: .\\flashbang\\Scripts\\python.exe tests\\check_occlusions.py"""

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
# migration is additive: init on an already-initialized db is a no-op
database.init_db()

course_id = database.create_course("Occ Course")
pdf_id = database.create_pdf(course_id, "occ.pdf", total_pages=4)

# --- round-trip
occ1 = database.save_occlusion(pdf_id, 2, 0.1, 0.2, 0.3, 0.15)
occ2 = database.save_occlusion(pdf_id, 3, 0.5, 0.5, 0.2, 0.2)
rows = database.get_occlusions(pdf_id)
assert [r["id"] for r in rows] == [occ1, occ2], "ordered by page then id"
assert rows[0]["page_number"] == 2 and abs(rows[0]["w"] - 0.3) < 1e-9

# --- clamping: box hanging off the right edge is trimmed to fit
occ3 = database.save_occlusion(pdf_id, 1, 0.9, 0.9, 0.5, 0.5)
row = next(r for r in database.get_occlusions(pdf_id) if r["id"] == occ3)
assert abs(row["x"] + row["w"] - 1.0) < 1e-9 and abs(row["y"] + row["h"] - 1.0) < 1e-9

# --- degenerate boxes rejected (accidental clicks)
for bad in [(0.5, 0.5, 0.001, 0.2), (0.5, 0.5, 0.2, 0.0), (1.0, 0.5, 0.5, 0.2)]:
    try:
        database.save_occlusion(pdf_id, 1, *bad)
        raise AssertionError(f"box {bad} should have been rejected")
    except ValueError:
        pass

# --- delete one
database.delete_occlusion(occ2)
assert [r["id"] for r in database.get_occlusions(pdf_id)] == [occ3, occ1]

# --- pdf delete cascades to its boxes
database.delete_pdf(pdf_id)
assert database.get_occlusions(pdf_id) == [], "boxes must die with their pdf"

os.unlink(tmp.name)
print("check_occlusions: ALL PASSED")
