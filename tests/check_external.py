r"""External study reports (NotebookLM round-trip): decay math, storage,
report parsing, and the honesty constraints. Offline — no model calls anywhere
in this path by design.

Run: .\flashbang\Scripts\python.exe tests\check_external.py
"""
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db
import vector_store
from mastery import external_retention, _STABILITY_SCALE
from generation import parse_study_report, build_study_prompt

# ---------------- decay math (pure, no db)
now = datetime(2026, 8, 2, 12, 0, 0)
fresh = external_retention(80, now.isoformat(), now)
assert abs(fresh - 0.8) < 1e-9, "a report applied right now is worth its score"
s3 = 3 * _STABILITY_SCALE
one_s = external_retention(100, (now - timedelta(days=s3)).isoformat(), now)
assert abs(one_s - math.exp(-1)) < 1e-6, "after one assumed-stability period it decays to 1/e"
week = external_retention(80, (now - timedelta(days=7)).isoformat(), now)
assert 0.3 < week < 0.5, f"a week-old 80% should be roughly half ({week:.2f})"
assert external_retention(150, now.isoformat(), now) == 1.0, "recall clamps at 100"
assert external_retention(-5, now.isoformat(), now) == 0.0, "and at 0"
assert external_retention(80, (now + timedelta(days=1)).isoformat(), now) == 0.8, \
    "a clock-skewed future timestamp doesn't inflate beyond its score"

# ---------------- report parsing (local, no model call)
good = '''Nice work overall — solid on encoding, shaky on gradients.

```json
{"topics": [
  {"id": 216, "recall": 85, "quizzed": 3, "gap": null},
  {"id": 194, "recall": 40, "quizzed": 2, "gap": "chain rule direction"}
]}
```'''
rows = parse_study_report(good)
assert [r["id"] for r in rows] == [216, 194]
assert rows[0]["recall"] == 85 and rows[0]["gap"] is None
assert rows[1]["gap"] == "chain rule direction"

unfenced = '{"topics": [{"id": 216, "recall": 120, "quizzed": 1, "gap": ""}]}'
rows = parse_study_report(unfenced)
assert rows[0]["recall"] == 100, "recall clamps on parse"
assert rows[0]["gap"] is None, "empty gap becomes None"

for bad in ("", "no json here at all", '```json\n{"nope": []}\n```',
            '{"topics": "not a list"}'):
    try:
        parse_study_report(bad)
        assert False, f"should have raised on {bad!r}"
    except ValueError:
        pass

# malformed entries are skipped, valid ones survive
mixed = '{"topics": [{"id": "x", "recall": 50}, {"id": 216, "recall": 70}]}'
rows = parse_study_report(mixed)
assert len(rows) == 1 and rows[0]["id"] == 216

# ---------------- the prompt embeds ids so the reply joins back exactly
prompt = build_study_prompt("RB2302", [{"id": 216, "title": "RNN Intuition and Encoding"}])
assert "id 216" in prompt and "RNN Intuition and Encoding" in prompt
assert "recall" in prompt and "json" in prompt.lower()
assert "flattery" in prompt.lower(), "the honesty instruction is part of the contract"

# ---------------- storage: newest wins, cascade with the topic
tmp = tempfile.mkdtemp(prefix="fb_ext_")
db.DB_PATH = os.path.join(tmp, "test.db")
vector_store.reset(path=os.path.join(tmp, "chroma"))
db.init_db()
course_id = db.create_course("Test")
pdf_id = db.create_pdf(course_id, "notes.pdf", total_pages=4)
db.save_topics(pdf_id, [{"title": "Encoding", "page_start": 1, "page_end": 4,
                         "est_minutes": 10, "kind": "content"}])
tid = db.get_topics(pdf_id=pdf_id)[0]["id"]

assert db.latest_external_reviews(pdf_id=pdf_id) == {}
db.add_external_review(tid, 60, quizzed=3, gaps="one-hot vs index")
db.add_external_review(tid, 85, quizzed=4)
latest = db.latest_external_reviews(pdf_id=pdf_id)
assert latest[tid]["recall_pct"] == 85, "the newest report wins"
assert db.latest_external_reviews(course_id=course_id)[tid]["recall_pct"] == 85
db.add_external_review(tid, 999)
assert db.latest_external_reviews(pdf_id=pdf_id)[tid]["recall_pct"] == 100, "clamped at write"

db.delete_topic(tid)
assert db.latest_external_reviews(pdf_id=pdf_id) == {}, "reviews cascade with their topic"

print("check_external: ALL PASSED")
