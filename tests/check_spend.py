"""Spend-tracker checks: pricing math, aggregation, unit costs. No API needed.
Run: .\\flashbang\\Scripts\\python.exe tests\\check_spend.py"""

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

from llm_utils import price_for, PRICES
import stats

# --- pricing: published rates, per 1M tokens
assert abs(price_for("gpt-4o-mini", 1_000_000, 0) - 0.15) < 1e-9
assert abs(price_for("gpt-4o-mini", 0, 1_000_000) - 0.60) < 1e-9
assert abs(price_for("gpt-4o", 1_000_000, 1_000_000) - 12.50) < 1e-9
# suffixed model ids resolve to their base rate
assert abs(price_for("gpt-4o-mini-2024-07-18", 1_000_000, 0) - 0.15) < 1e-9
# an unknown model must NOT be free — spend can't be silently understated
assert price_for("some-new-model", 1_000_000, 0) > 0

# --- empty state
empty = stats.compute_spend()
assert empty["calls"] == 0 and empty["total"] == 0.0 and empty["by_purpose"] == []

# --- logging + aggregation
database.log_llm_call("grading", "gpt-4o-mini", 700, 80, price_for("gpt-4o-mini", 700, 80))
database.log_llm_call("grading", "gpt-4o-mini", 700, 80, price_for("gpt-4o-mini", 700, 80))
database.log_llm_call("card generation", "gpt-4o", 1200, 600, price_for("gpt-4o", 1200, 600))
database.log_llm_call("segmentation", "gpt-4o", 25000, 800, price_for("gpt-4o", 25000, 800))

sp = stats.compute_spend()
assert sp["calls"] == 4
expected = (2 * price_for("gpt-4o-mini", 700, 80) + price_for("gpt-4o", 1200, 600)
            + price_for("gpt-4o", 25000, 800))
assert abs(sp["total"] - round(expected, 4)) < 1e-4, (sp["total"], expected)
assert sp["today"] == sp["total"] and sp["week"] == sp["total"], "all logged today"

# ordered biggest-first, and segmentation dominates this set
assert sp["by_purpose"][0]["purpose"] == "segmentation", sp["by_purpose"]
assert sp["biggest"] == "segmentation"
grading = next(p for p in sp["by_purpose"] if p["purpose"] == "grading")
assert grading["calls"] == 2 and grading["tokens"] == 2 * 780

# --- unit costs: per graded answer, and per card once cards exist
assert abs(sp["per_answer"] - round(price_for("gpt-4o-mini", 700, 80), 5)) < 1e-5
assert sp["per_card"] is None, "no cards yet -> no per-card figure"

course = database.create_course("Spend Course")
pdf = database.create_pdf(course, "s.pdf", total_pages=2)
tid = database.save_topics(pdf, [
    {"title": "T", "summary": "", "page_start": 1, "page_end": 2, "est_minutes": 10}])[0]
for i in range(4):
    database.insert_card(tid, f"Q{i}?", "A.")
sp = stats.compute_spend()
gen_cost = price_for("gpt-4o", 1200, 600)
assert abs(sp["per_card"] - round(gen_cost / 4, 4)) < 1e-4, sp["per_card"]

# --- 14-day series always covers the window, newest last
assert len(sp["days"]) == 14
assert sp["days"][-1]["date"] == datetime.now().date().isoformat()
assert sp["days"][-1]["usd"] > 0 and sp["days"][0]["usd"] == 0

# --- a logging failure must never break the caller
database.log_llm_call("weird", None, None, None, None)   # tolerated, no raise

# --- vision page selection: sparse-only by default, everything when forced
from pdf_ingest import pages_needing_vision, SPARSE_THRESHOLD
sample = [
    {"page_number": 1, "text": ""},                        # blank / scanned
    {"page_number": 2, "text": "x" * (SPARSE_THRESHOLD - 1)},   # sparse
    {"page_number": 3, "text": "x" * (SPARSE_THRESHOLD + 500)}, # text-rich
]
assert pages_needing_vision(sample) == [1, 2], "only sparse pages by default"
assert pages_needing_vision(sample, force_vision=True) == [1, 2, 3], "forced = every page"
assert pages_needing_vision([], force_vision=True) == []

# --- transient-retry layer: 429/5xx-style failures retry, logic errors don't
import llm_utils
llm_utils._sleep = lambda s: None   # no real waiting in tests

class Boom(Exception):
    def __init__(self, status=None):
        self.status_code = status

calls = {"n": 0}
def flaky():
    calls["n"] += 1
    if calls["n"] < 3:
        raise Boom(429)
    return "ok"
assert llm_utils._with_retries(flaky) == "ok" and calls["n"] == 3

def always_down():
    raise Boom(503)
try:
    llm_utils._with_retries(always_down)
    assert False, "must raise once retries are exhausted"
except Boom:
    pass

calls["n"] = 0
def logic_error():
    calls["n"] += 1
    raise ValueError("bad prompt")
try:
    llm_utils._with_retries(logic_error)
    assert False, "non-transient errors must surface immediately"
except ValueError:
    pass
assert calls["n"] == 1, "non-transient errors must not retry"

os.unlink(tmp.name)
print("check_spend: ALL PASSED")
