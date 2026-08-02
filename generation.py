from llm_utils import call_for_json, complete_text
from database import get_topic, get_pdf, get_courses, get_pdf_pages


def extract_concepts(notes, subject, topic_title):
    """Extract key concepts (with verbatim source text) from a block of notes.
    subject and topic_title are SUPPLIED (course name / topic title), never
    inferred — a wrong guess here would propagate into every card."""
    prompt = f"""You are an expert at reading study notes and identifying the key concepts within them.

TASK:
Read the notes below and identify the key concepts. For each concept, extract the exact verbatim text from the notes that pertains to it.

Subject: {subject}
Topic: {topic_title}

Key concepts are important ideas or principles essential to understanding the material or solving problems related to the topic. They often include definitions, formulas, processes, or relationships between ideas.

Rules:
- "content" must be the exact verbatim text from the notes that pertains to the concept — including any examples, formulas, or code blocks. Do not paraphrase, summarize, or rewrite.
- If a passage pertains to more than one concept, include it under both concepts.
- Put any text that does not pertain to any concept verbatim in the "uncategorized" field so nothing is silently dropped.
- Focus on content that genuinely helps understanding. Skip fun facts, historical asides, and other non-essential material.

<notes>
{notes}
</notes>

OUTPUT FORMAT:
Respond with ONLY a JSON object in this exact format. No markdown code fences, no preamble:
{{
    "concepts": [
        {{
            "name": "<string, short concept name, e.g. 'method overriding'>",
            "content": "<string, verbatim text from the notes pertaining to this concept>"
        }}
    ],
    "uncategorized": "<string, verbatim leftover text that fit no concept, or empty string>"
}}
"""
    return call_for_json(prompt, max_tokens=4000, purpose="concept extraction")


def generate_cards(subject, topic_title, concepts, count):
    """Generate up to `count` question/answer cards for a batch of concepts.
    Returns [{"question", "answer"}] — identity (course/pdf/topic) is carried
    by foreign keys at insert time, not by the model."""
    count = min(count, 80)
    concepts_text = "\n\n".join(
        f"Concept: {c['name']}\nContent: {c['content']}"
        for c in concepts
    )

    prompt = f"""You are an educator creating flashcards for students based on key concepts and the source text tied to those concepts.

INPUTS:
Subject: {subject}
Topic: {topic_title}

The concepts and their verbatim text:
{concepts_text}

TASK:
Create up to {count} flashcards from these concepts — only as many as the content genuinely supports; never invent or pad.

Rules (grounded in the card-formulation research — Wozniak's minimum-information principle, retrieval practice, elaborative interrogation):
- MINIMUM INFORMATION: one fact per card. If a sentence in the source uses 'and', 'or', or lists items, those items must become separate cards. For example: 'open addressing uses linear probing or quadratic probing' should produce THREE cards (one on open addressing, one on linear probing, one on quadratic probing), not one bundled card. Simple cards are answered fast and schedule accurately; compound cards fail on their weakest part.
- CONTEXT-FREE: every question must be answerable on its own weeks later, with no memory of the deck. Name the thing being asked about — never 'this method', 'the algorithm above', or 'step 2'.
- FORCED RECALL, never recognition: no yes/no or true/false questions (guessable at 50%). Rephrase as what/why/how so the answer must be generated from memory.
- Mix factual recall ('what...') with 'why'/'how' questions — explanatory questions build the understanding that transfers (elaborative interrogation).
- CLOZE for formulas and precise phrasings: ask for one missing part ("In F = ma, what does m stand for?") rather than the whole formula at once.
- FIGHT INTERFERENCE: when the source contains two easily-confused ideas (e.g. overriding vs overloading), add ONE explicit discrimination card ("How does X differ from Y?") alongside their individual cards.
- BIDIRECTIONAL only for the most important terms: term→definition plus definition→term doubles the retrieval routes; reserve it for the concepts the topic centers on, not every card.
- ANCHOR IN EXAMPLES: if the source gives a concrete example, prefer asking about the concept THROUGH the example ("Why does the currency-converter subclass override convert()?") over abstract restatement.
- Questions must be unambiguous with a single correct answer directly supported by the verbatim text. No opinion-based or open-ended questions, and none that require synthesizing multiple concepts.
- Do not create questions whose answers are lists or sets of items — make one card per item instead.
- For code-related cards, test concepts over derivable facts: ask what the code is for or how it works, not what its output is.
- You may paraphrase the source for clarity, but the meaning must be fully preserved.
- Answers should be 1 to 3 sentences: long enough to include reasoning, short enough to recall.

EXAMPLE OUTPUT:
[
    {{
        "question": "Where do the light-dependent reactions of photosynthesis take place?",
        "answer": "In the thylakoid membranes of the chloroplast."
    }},
    {{
        "question": "Why do most plants appear green?",
        "answer": "Chlorophyll absorbs light strongly in the blue and red regions of the visible spectrum and reflects green light, which is what reaches our eyes."
    }}
]

OUTPUT FORMAT:
Respond with ONLY a JSON array of objects with "question" and "answer" string fields. No markdown code fences, no preamble.
"""
    return call_for_json(prompt, max_tokens=4000, purpose="card generation")


def get_topic_text(topic_id):
    """Assemble a topic's source text from its stored pdf pages."""
    topic = get_topic(topic_id)
    if topic is None:
        raise ValueError(f"No topic with id {topic_id}")
    pages = get_pdf_pages(topic["pdf_id"], topic["page_start"], topic["page_end"])
    return "\n\n".join(f"=== PAGE {p['page_number']} ===\n{p['text']}" for p in pages), topic


def extract_topic_concepts(topic_id):
    """Run concept extraction over a topic's page range. Subject comes from the
    course, topic title from the topic row. Chunks very long topics."""
    text, topic = get_topic_text(topic_id)
    course_name = _course_name(topic["course_id"])

    CHUNK_CHARS = 60_000
    if len(text) <= CHUNK_CHARS:
        result = extract_concepts(text, course_name, topic["title"])
        return result.get("concepts", [])

    concepts = []
    for start in range(0, len(text), CHUNK_CHARS):
        chunk = text[start:start + CHUNK_CHARS]
        result = extract_concepts(chunk, course_name, topic["title"])
        concepts.extend(result.get("concepts", []))
    return concepts


def generate_cards_for_topic(topic_id, concepts, note_ids, per_concept_cap=5, total_cap=80):
    """Generate cards concept-by-concept so each card can be tagged with its
    source note_id. Returns card dicts ready for bulk_insert_cards."""
    topic = get_topic(topic_id)
    if topic is None:
        raise ValueError(f"No topic with id {topic_id}")
    course_name = _course_name(topic["course_id"])

    all_cards = []
    for concept, note_id in zip(concepts, note_ids):
        if len(all_cards) >= total_cap:
            break
        cap = min(per_concept_cap, total_cap - len(all_cards))
        cards = generate_cards(course_name, topic["title"], [concept], cap)
        for card in cards:
            card["topic_id"] = topic_id
            card["note_id"] = note_id
        all_cards.extend(cards)
    return all_cards


def generate_pretest(pdf_id, count=5):
    """Pretest questions for a document the user hasn't studied yet (pretesting
    effect: attempting answers before reading primes later learning). Samples
    pages evenly across the document. Not graded, never touches SM-2."""
    count = max(3, min(count or 5, 5))
    pages = get_pdf_pages(pdf_id)
    if not pages:
        raise ValueError(f"No stored pages for pdf {pdf_id}")

    BUDGET = 15_000
    step = max(1, len(pages) // 8)
    sampled, used = [], 0
    for page in pages[::step]:
        block = f"=== PAGE {page['page_number']} ===\n{page['text']}"
        if used + len(block) > BUDGET:
            break
        sampled.append(block)
        used += len(block)

    pdf = get_pdf(pdf_id)
    course_name = _course_name(pdf["course_id"]) if pdf else "Unknown"

    prompt = f"""You are writing a PRETEST for study material the student has NOT read yet ("{pdf['filename']}", course: {course_name}). The goal is the pretesting effect: attempting these questions before reading — and mostly getting them wrong — primes the brain to encode the answers when they appear in the material.

Rules:
- Write exactly {count} questions spanning different parts of the document (excerpts below are sampled across it).
- Target the document's central concepts — things the student WILL learn, phrased so an attempt is possible from general knowledge.
- Mix conceptual ("why/how") with factual ("what/which").
- Each answer: 1-2 sentences, from the material.

<excerpts>
{chr(10).join(sampled)}
</excerpts>

OUTPUT FORMAT:
Respond with ONLY a JSON array. No markdown fences, no preamble:
[{{"question": "<string>", "answer": "<string>"}}]
"""
    return call_for_json(prompt, max_tokens=2000, purpose="pretest")


def generate_primer(topic_id):
    """The 'don't go in blind' card for a topic: a gist, ONE concrete analogy
    with its mapping and its limits, the ideas you'll meet, and the assumed
    prior knowledge.

    Why this exists: comprehension depends on having somewhere to put new
    information (Ausubel's advance organizers; Mayer's pre-training principle).
    Reading cold means decoding sentence by sentence with nothing to attach
    them to.

    Why the analogy carries a MAPPING and a BREAKS field: an unbounded analogy
    is how misconceptions get installed. A student who is told 'an electron is
    a planet' and never told where that stops will defend the orbit later. The
    mapping makes the correspondence explicit and `breaks` marks the edge.

    One fast-tier call, cached in topic_primers — opening a topic twice is free.
    """
    text, topic = get_topic_text(topic_id)
    course_name = _course_name(topic["course_id"])
    if not text.strip():
        raise ValueError("No stored page text for this topic")
    excerpt = text[:18_000]

    prompt = f"""Write a PRIMER for a student who is about to read this material for the first time and currently knows nothing about it. Topic: "{topic['title']}" (course: {course_name}).

The primer is read BEFORE the material. Its whole job is to give the student somewhere to put what they are about to read.

Write:

1. "gist" — ONE short paragraph, 2-3 sentences, giving the single central idea. What is this topic actually about, and what does it let you DO once you have it? Plain language, no jargon the material hasn't earned yet. Do not say "this topic covers"; say what the idea IS.

2. THEN exactly one of these two, never both — pick whichever the material actually is:
   - "detail": a second short paragraph (2-3 sentences) when the topic is ONE CONTINUOUS IDEA that needs a little more room. Set "points" to [].
   - "points": 2-4 one-line bullets when the topic is a SET OF DISTINCT parts, steps, cases or contrasts. Each bullet is a complete thought, under 18 words. Set "detail" to null.
   Do not force bullets onto an idea that isn't a list, and do not pad a list into prose.
   You may bold a key term with **double asterisks**, three at most across the whole overview.

2. "analogy" — ONE concrete, everyday analogy that paints a picture. 2-3 sentences. It must be something an ordinary person has physically seen or done — a kitchen, a post office, a queue, a set of drawers, a recipe. NOT another technical domain. Make it specific and visual: a named object doing a named thing, not "it's like a system that processes data".

3. "mapping" — 3-4 pairs tying the analogy to the real thing, so the picture actually teaches instead of just decorating. Each pair: "this" = the part of the analogy, "is" = what it corresponds to in the material.

4. "breaks" — one sentence naming where the analogy stops being true. This is required. An analogy nobody bounded is how a misconception gets installed.

5. "ideas" — 3-5 short names of the specific things the student will meet in the reading (terms, mechanisms, distinctions). Two to five words each. These are hooks, not definitions.

6. "prereq" — one sentence: what the student is assumed to already know walking in. If genuinely nothing, say so plainly.

Ground everything in the excerpt. If the excerpt is thin, write a shorter primer rather than inventing material.

<excerpt>
{excerpt}
</excerpt>

OUTPUT FORMAT:
Respond with ONLY a JSON object. No markdown fences, no preamble:
{{"gist": "<string, one paragraph>",
 "detail": "<string, a second paragraph — or null if you used points>",
 "points": ["<string>"],
 "analogy": "<string>",
 "mapping": [{{"this": "<part of the analogy>", "is": "<what it maps to>"}}],
 "breaks": "<string>",
 "ideas": ["<string>"],
 "prereq": "<string>"}}
"""
    primer = call_for_json(prompt, fast=True, max_tokens=1200, purpose="topic primer")

    # The overview's SHAPE comes from the schema, not from formatting rules
    # inside a string: asking for paragraph breaks and "- " bullets inside a
    # JSON field gets ignored about half the time, whereas separate fields get
    # filled reliably. Compose them into the markdown the reader renders,
    # taking at most one of detail/points if the model returns both.
    blocks = [(primer.get("gist") or "").strip()]
    detail = (primer.get("detail") or "").strip()
    points = [p.strip() for p in (primer.get("points") or []) if str(p).strip()]
    if points:
        blocks.append("\n".join(f"- {p}" for p in points[:4]))
    elif detail:
        blocks.append(detail)
    primer["gist"] = "\n\n".join(b for b in blocks if b)
    primer.pop("detail", None)
    primer.pop("points", None)
    return primer


""" ---------------------------------------------------------------- primer diagram """

# Model-written SVG is injected into the page, so it is treated as untrusted
# input: rebuilt element by element from an allow-list rather than filtered.
# A blocklist would have to anticipate every vector — <script>, onload=,
# <foreignObject>, xlink:href to a remote doc — and only has to be wrong once.
_SVG_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
             "polygon", "text", "tspan", "defs", "marker", "title", "desc"}
_SVG_ATTRS = {"viewbox", "d", "x", "y", "cx", "cy", "r", "rx", "ry", "x1", "y1", "x2", "y2",
              "width", "height", "points", "fill", "stroke", "stroke-width", "stroke-linecap",
              "stroke-linejoin", "stroke-dasharray", "fill-opacity", "stroke-opacity", "opacity",
              "transform", "font-size", "font-family", "font-weight", "text-anchor",
              "dominant-baseline", "marker-end", "marker-start", "id", "orient",
              "refx", "refy", "markerwidth", "markerheight", "markerunits",
              "role", "aria-label", "text-transform", "letter-spacing"}
# canonical attribute spellings — XML is case-sensitive where SVG cares
_SVG_CANON = {"viewbox": "viewBox", "refx": "refX", "refy": "refY",
              "markerwidth": "markerWidth", "markerheight": "markerHeight",
              "markerunits": "markerUnits"}


def sanitize_svg(raw):
    """Rebuild an SVG from an allow-list of tags and attributes. Returns the
    cleaned markup, or None if it isn't a usable SVG."""
    import re
    import xml.etree.ElementTree as ET

    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):                     # strip a stray fence
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    start = text.find("<svg")
    if start == -1:
        return None
    text = text[start:]
    end = text.rfind("</svg>")
    if end == -1:
        return None
    text = text[:end + 6]

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None

    def strip_ns(tag):
        return tag.split("}")[-1].lower() if isinstance(tag, str) else ""

    def clean(el):
        tag = strip_ns(el.tag)
        if tag not in _SVG_TAGS:
            return None
        out = ET.Element(tag)
        for k, v in el.attrib.items():
            key = strip_ns(k)
            if key not in _SVG_ATTRS:
                continue
            val = str(v)
            # url(#id) is fine; anything reaching outside the document is not
            if "javascript:" in val.lower() or "://" in val:
                continue
            out.set(_SVG_CANON.get(key, key), val)
        if el.text and el.text.strip():
            out.text = el.text
        for child in el:
            kept = clean(child)
            if kept is not None:
                out.append(kept)
            if child.tail and child.tail.strip():
                (kept if kept is not None else out).tail = child.tail
        return out

    cleaned = clean(root)
    if cleaned is None or strip_ns(root.tag) != "svg":
        return None
    if cleaned.get("viewBox") is None:
        return None                                # without one it cannot scale
    # let the container size it
    cleaned.attrib.pop("width", None)
    cleaned.attrib.pop("height", None)
    return ET.tostring(cleaned, encoding="unicode")


def generate_primer_diagram(topic_id, primer, fast=False):
    """Draw the primer's analogy as a labelled SVG.

    SVG rather than a generated image on purpose: an image model cannot render
    correct labels, and an unlabelled picture cannot carry the mapping — which
    is the part that teaches. SVG also scales, inherits the palette, and costs
    a fraction of a raster image.

    Second call, second button: a primer is complete without a diagram.
    """
    topic = get_topic(topic_id)
    if topic is None:
        raise ValueError(f"No topic with id {topic_id}")
    mapping = primer.get("mapping") or []
    if not primer.get("analogy"):
        raise ValueError("This primer has no analogy to draw")

    pairs = "\n".join(f'- "{m.get("this","")}" means "{m.get("is","")}"' for m in mapping)
    prompt = f"""Draw ONE diagram, as SVG, of the analogy below. The reader has not read the material yet — the picture's job is to make the analogy concrete and to LABEL which part means what.

Topic: "{topic['title']}"
The analogy: {primer['analogy']}
What maps to what:
{pairs or "(no mapping given — label the parts sensibly)"}

Requirements:
- ONE <svg> element with viewBox="0 0 420 300" and NO width/height attributes.
- Draw the ANALOGY's objects — the literal thing described — not boxes labelled with abstract words. If the analogy is plates, draw plates.
- Every mapped part gets a short <text> label saying what it means. Labels are real <text> elements, font-size 9 to 11.5, never below 9.
- Palette ONLY: #0A0A0A (ink lines and type), #6B6B6B (secondary type), #DCDCDC (hairlines), #1B4FD8 (cobalt — use it for exactly ONE thing: the single most important part). No other colours. No gradients, no shadows, no filters.
- Flat line art: strokes 1.5-2, fills either none or a colour at low fill-opacity.
- font-family="'IBM Plex Sans',sans-serif" on prose labels, "'IBM Plex Mono',monospace" on code-like ones.
- Keep everything inside the 420x300 box with a 20px margin. Nothing may overlap another label.
- Allowed elements only: svg, g, path, rect, circle, ellipse, line, polyline, polygon, text, tspan, defs, marker, title, desc. No script, no style, no foreignObject, no image, no external references.
- Include a <title> describing the picture for screen readers.

Respond with ONLY the SVG markup. No prose, no markdown fences."""

    # Drawing defaults to the MAIN model. The diagram prompt carries only the
    # analogy and its mapping — not the page text — so the input is tiny and
    # the main model costs cents, not dollars. Spatial layout is the one thing
    # the fast tier is measurably bad at, and a wrong picture is worse than no
    # picture, so this is the wrong place to save a fraction of a cent.
    raw, _ = complete_text(prompt, fast=fast, max_tokens=2200, purpose="primer diagram")
    svg = sanitize_svg(raw)
    if not svg:
        raise ValueError("The model didn't return a usable SVG")
    return svg


def parse_flashcards(text):
    """Parse pasted flashcards (NotebookLM output, Anki exports, hand-typed
    lists) into [{'question','answer'}]. Deterministic formats first:
    one-card-per-line with a TAB / ' :: ' / ';;' / '|' separator, or
    Q:/A: (also Question:/Answer:, Front:/Back:) blocks. If nothing
    parses, one fast-tier LLM call extracts the pairs.
    Returns (cards, source) where source is 'parsed' or 'ai'."""
    text = (text or "").strip()
    if not text:
        return [], "parsed"

    cards = []
    # per-line separators
    for sep in ("\t", " :: ", ";;", "|"):
        cards = []
        for line in text.splitlines():
            if sep not in line:
                continue
            parts = [p.strip() for p in line.split(sep)]
            parts = [p for p in parts if p]
            if len(parts) == 2:
                cards.append({"question": parts[0], "answer": parts[1]})
        if len(cards) >= 2 or (cards and len(text.splitlines()) <= 2):
            return cards, "parsed"

    # Q:/A: blocks
    import re
    q_re = re.compile(r"^\s*(?:Q|Question|Front)\s*[:.)]\s*(.*)", re.I)
    a_re = re.compile(r"^\s*(?:A|Answer|Back)\s*[:.)]\s*(.*)", re.I)
    cards, question, answer, in_answer = [], None, None, False
    def flush():
        if question and answer:
            cards.append({"question": question.strip(), "answer": answer.strip()})
    for line in text.splitlines():
        qm, am = q_re.match(line), a_re.match(line)
        if qm:
            flush()
            question, answer, in_answer = qm.group(1), None, False
        elif am and question is not None:
            answer, in_answer = am.group(1), True
        elif in_answer and line.strip():
            answer += " " + line.strip()
        elif question is not None and not in_answer and line.strip():
            question += " " + line.strip()
    flush()
    if cards:
        return cards, "parsed"

    # free-form -> one cheap structured call
    prompt = f"""Extract the flashcards from the pasted text below into JSON.
Rules: keep question and answer wording as close to the source as possible;
skip headings, source references, and commentary that is not a card; if the
text contains no recognizable flashcards, return [].

<pasted>
{text[:20000]}
</pasted>

Respond with ONLY a JSON array: [{{"question": "<string>", "answer": "<string>"}}]"""
    result = call_for_json(prompt, fast=True, max_tokens=4000, purpose="import parsing")
    good = [c for c in result if isinstance(c, dict)
            and (c.get("question") or "").strip() and (c.get("answer") or "").strip()]
    return good, "ai"


def _course_name(course_id):
    for course in get_courses():
        if course["id"] == course_id:
            return course["name"]
    return "Unknown"
