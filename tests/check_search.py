"""Search checks against a REAL temp Chroma collection with local embeddings —
no API, no stubs. First run downloads Chroma's ONNX MiniLM model (~80 MB).
Run: .\\flashbang\\Scripts\\python.exe tests\\check_search.py"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import vector_store

# isolate both stores
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
database.DB_PATH = tmp.name
database.init_db()
chroma_dir = tempfile.mkdtemp(prefix="chroma_test_")
vector_store.reset(path=chroma_dir)

import search

course_id = database.create_course("CS")
pdf_id = database.create_pdf(course_id, "notes.pdf", total_pages=2)
database.save_pdf_pages(pdf_id, [{"page_number": 1, "text": "x", "extractor": "pypdf"}])
topic_ids = database.save_topics(pdf_id, [
    {"title": "Hashing", "summary": "", "page_start": 1, "page_end": 1, "est_minutes": 10},
    {"title": "Biology", "summary": "", "page_start": 2, "page_end": 2, "est_minutes": 10},
])

database.save_concepts(topic_ids[0], [
    {"name": "chaining", "content": "Hash tables resolve collisions by chaining: each slot holds a linked list of entries whose keys hash to the same index."},
])
database.save_concepts(topic_ids[1], [
    {"name": "photosynthesis", "content": "Photosynthesis converts light energy into glucose inside the chloroplasts of plant cells."},
])

# semantically related query ranks the hashing note first, with citation metadata
results = search.search_notes("how do hash tables handle collisions", top_k=2, min_score=0.0)
assert results, "no results returned"
score, top = results[0]
assert top["name"] == "chaining", f"wrong top hit: {top}"
assert top["course_name"] == "CS" and top["topic_title"] == "Hashing", "citation metadata missing"
assert score > 0.3, f"suspiciously low similarity for a direct match: {score}"
if len(results) > 1:
    assert results[0][0] > results[1][0], "ranking not descending"

# metadata filter restricts to a topic
results = search.search_notes("energy", top_k=5, min_score=-1.0, topic_id=topic_ids[1])
assert results and all(r["topic_title"] == "Biology" for _, r in results)

# min_score gate filters weak matches
results = search.search_notes("completely unrelated quantum finance topic",
                              top_k=5, min_score=0.9)
assert results == [], f"min_score gate failed: {results}"

# deleting a note removes it from the vector store
conn = database.get_conn()
all_notes = conn.execute("SELECT id FROM notes").fetchall()
conn.close()  # Windows can't unlink the temp DB with a connection open
first_note = all_notes[0]["id"]
database.delete_note(first_note)
results = search.search_notes("hash table collision chaining", top_k=5, min_score=0.0)
assert all(r["id"] != first_note for _, r in results), "deleted note still searchable"

os.unlink(tmp.name)
print("check_search: ALL PASSED (Chroma, local embeddings)")
