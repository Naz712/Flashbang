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

# ---- the diagram column is independent of the primer text
# (the cascade check above deleted the first topic, so this needs its own)
db.save_topics(pdf_id, [{"title": "Iteration", "page_start": 1, "page_end": 2,
                         "est_minutes": 10, "kind": "content"}])
svg_topic = [t for t in db.get_topics(pdf_id=pdf_id) if t["title"] == "Iteration"][0]["id"]
db.save_primer(svg_topic, primer)
assert db.get_primer(svg_topic).get("svg") is None, "a primer starts with no drawing"
db.save_primer_svg(svg_topic, '<svg viewBox="0 0 10 10"></svg>')
assert db.get_primer(svg_topic)["svg"].startswith("<svg"), "drawing attaches"
assert db.get_primer(svg_topic)["gist"] == primer["gist"], "attaching a drawing must not touch the text"
db.save_primer_svg(svg_topic, None)
assert db.get_primer(svg_topic)["svg"] is None, "drawing clears without losing the primer"
assert db.get_primer(svg_topic)["gist"] == primer["gist"], "clearing a drawing must not touch the text"

# ---- SVG SANITISER. Model-written markup goes straight into the page, so this
# is a security boundary, not a formatting nicety. Rebuild-from-allow-list, so
# anything not explicitly permitted is gone rather than filtered.
from generation import sanitize_svg

VECTORS = {
    "script tag": '<svg viewBox="0 0 10 10"><script>alert(1)</script><rect x="1" y="1" width="2" height="2"/></svg>',
    "event handler": '<svg viewBox="0 0 10 10"><rect x="1" y="1" width="2" height="2" onload="alert(1)"/></svg>',
    "remote image": '<svg viewBox="0 0 10 10"><image href="https://evil.example/x.png"/></svg>',
    "javascript: url": '<svg viewBox="0 0 10 10"><rect fill="javascript:alert(1)" x="1" y="1" width="2" height="2"/></svg>',
    "style tag": '<svg viewBox="0 0 10 10"><style>*{background:url(https://evil)}</style><circle cx="5" cy="5" r="2"/></svg>',
}
BANNED = ("script", "onload", "onerror", "foreignobject", "javascript:", "<style", "://")
for name, raw in VECTORS.items():
    out = sanitize_svg(raw) or ""
    low = out.lower()
    for bad in BANNED:
        assert bad not in low, f"{name}: sanitiser leaked {bad!r} -> {out}"

assert sanitize_svg('<svg viewBox="0 0 10 10"><foreignObject><b>x</b></foreignObject></svg>') in (None, '<svg viewBox="0 0 10 10" />'), \
    "foreignObject must not survive"
assert sanitize_svg('<svg width="10" height="10"><rect/></svg>') is None, "no viewBox = not usable"
assert sanitize_svg("sorry, I can't draw that") is None, "prose is not an SVG"
assert sanitize_svg("") is None and sanitize_svg(None) is None

good = sanitize_svg('```svg\n<svg viewBox="0 0 420 300" width="420" height="300">'
                    '<title>a stack</title><ellipse cx="150" cy="240" rx="72" ry="13" '
                    'fill="none" stroke="#0A0A0A" stroke-width="1.5"/>'
                    '<text x="150" y="246" font-size="9" fill="#6B6B6B">main()</text></svg>\n```')
assert good and good.startswith("<svg"), "a clean SVG survives, fence and all"
assert 'viewBox="0 0 420 300"' in good, "viewBox is preserved"
assert "main()" in good, "label text is preserved"
assert "<title>" in good, "the accessible title is preserved"
# only on the ROOT tag — stroke-width on a child is legitimate and must survive
root_tag = good[:good.index(">") + 1]
assert " width=" not in root_tag and " height=" not in root_tag, \
    f"root width/height must be stripped so the container sizes it: {root_tag}"
assert "stroke-width" in good, "stroke-width on children must survive"

# ---- a found diagram is stored WITH its attribution and is independent too
db.save_primer_image(svg_topic, {"title": "Call-stack-layout.svg", "thumb": "https://x/y.png",
                                 "page": "https://commons.wikimedia.org/wiki/File:x",
                                 "license": "CC BY-SA 2.5", "artist": "Cameron McCormack"})
img = db.get_primer(svg_topic)["image"]
assert isinstance(img, dict), "the image comes back parsed"
assert img["license"] and img["artist"], "attribution is stored, not just the URL"
assert db.get_primer(svg_topic)["gist"] == primer["gist"], "pinning an image must not touch the text"
db.save_primer_image(svg_topic, None)
assert db.get_primer(svg_topic)["image"] is None, "image clears"
assert db.get_primer(svg_topic)["gist"] == primer["gist"], "clearing must not touch the text"

print("check_primer: ALL PASSED")
