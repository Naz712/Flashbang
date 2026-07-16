"""End-to-end ingestion check against a REAL pdf. Needs ANTHROPIC_API_KEY in .env.
Run: .\\flashbang\\Scripts\\python.exe tests\\check_ingest.py <path-to-pdf>"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if len(sys.argv) < 2:
    print("usage: check_ingest.py <path-to-pdf>")
    sys.exit(1)
pdf_path = sys.argv[1]

import database

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
database.DB_PATH = tmp.name
database.init_db()

from pdf_ingest import read_pdf, propose_topics

course_id = database.create_course("Ingest Check")
stats = read_pdf(pdf_path, course_id)
print(f"read_pdf: {stats}")
assert stats["total_pages"] > 0

# every page persisted
pages = database.get_pdf_pages(stats["pdf_id"])
assert len(pages) == stats["total_pages"], f"{len(pages)} pages stored vs {stats['total_pages']} in pdf"
assert [p["page_number"] for p in pages] == list(range(1, stats["total_pages"] + 1))

proposal = propose_topics(stats["pdf_id"])
topics = proposal["topics"]
print(f"\n{len(topics)} topics, est total {proposal['est_total_hours']} h:")
for t in topics:
    print(f"  p.{t['page_start']}-{t['page_end']}  ~{t['est_minutes']} min  {t['title']}")

# ranges contiguous, in bounds, minutes sane
assert topics, "no topics proposed"
assert topics[0]["page_start"] == 1
assert topics[-1]["page_end"] == stats["total_pages"]
for prev, cur in zip(topics, topics[1:]):
    assert cur["page_start"] == prev["page_end"] + 1, \
        f"gap/overlap between '{prev['title']}' and '{cur['title']}'"
for t in topics:
    assert t["page_start"] <= t["page_end"]
    assert t["est_minutes"] > 0, f"topic '{t['title']}' has no time estimate"

# saving syncs the pdf total
database.save_topics(stats["pdf_id"], topics)
pdf = database.get_pdf(stats["pdf_id"])
assert pdf["est_total_minutes"] == sum(t["est_minutes"] for t in topics)
assert pdf["status"] == "ready"

os.unlink(tmp.name)
print("\ncheck_ingest: ALL PASSED")
