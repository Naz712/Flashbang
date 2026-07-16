"""Search ranking checks with stubbed embeddings — no API needed.
Run: .\\flashbang\\Scripts\\python.exe tests\\check_search.py"""

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import embeddings

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
database.DB_PATH = tmp.name
database.init_db()

# stub embed_text BEFORE importing search (search binds database fns at import;
# embeddings are looked up via module attr in database.save_concepts... they are
# imported directly, so stub the function object attribute both places)
FAKE = {
    "hash tables": [1.0, 0.0, 0.0],
    "hash collision chaining": [0.9, 0.1, 0.0],
    "photosynthesis": [0.0, 1.0, 0.0],
}


def fake_embed(text):
    return FAKE.get(text, [0.0, 0.0, 1.0])


embeddings.embed_text = fake_embed
database.embed_text = fake_embed  # database.py did `from embeddings import embed_text`

import search
search.embed_text = fake_embed    # search.py too

course_id = database.create_course("CS")
pdf_id = database.create_pdf(course_id, "notes.pdf", total_pages=2)
database.save_pdf_pages(pdf_id, [{"page_number": 1, "text": "x", "extractor": "pypdf"}])
topic_ids = database.save_topics(pdf_id, [
    {"title": "Hashing", "summary": "", "page_start": 1, "page_end": 1, "est_minutes": 10},
    {"title": "Biology", "summary": "", "page_start": 2, "page_end": 2, "est_minutes": 10},
])

database.save_concepts(topic_ids[0], [{"name": "chaining", "content": "hash collision chaining"}])
database.save_concepts(topic_ids[1], [{"name": "photo", "content": "photosynthesis"}])

results = search.search_notes("hash tables", top_k=2, min_score=0.3)
assert len(results) == 1, f"expected only the hashing note above 0.3, got {len(results)}"
score, row = results[0]
assert row["name"] == "chaining"
assert score > 0.85
assert row["course_name"] == "CS" and row["topic_title"] == "Hashing", "join columns missing"

# filter by topic excludes the other note entirely
results = search.search_notes("hash tables", top_k=5, min_score=0.0, topic_id=topic_ids[1])
assert all(r["topic_title"] == "Biology" for _, r in results)

os.unlink(tmp.name)
print("check_search: ALL PASSED")
