from llm_utils import call_for_json
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


def split_tutorial(pdf_id, topics):
    """Split a tutorial paper into individual questions and tag each with the
    student's OWN note topics.

    Splitting and tagging in ONE call, not two: the model has to read the
    question to split it, and asking again later would pay for that reading
    twice. Tags are chosen from a supplied list rather than invented, because
    the whole point is to join back to the topics in their notes — a free-text
    tag that reads "recursion basics" cannot be matched to topic 91.

    Each LEAF part is its own question: 3(a) and 3(b) are separate rows sharing
    a group, so a flag can say which part actually confused you.
    """
    pages = get_pdf_pages(pdf_id)
    if not pages:
        raise ValueError("No stored page text for this tutorial")
    body = "\n\n".join(f"=== PAGE {p['page_number']} ===\n{p['text']}" for p in pages)[:60_000]
    topic_list = "\n".join(f'{t["id"]}: {t["title"]}' for t in topics) or "(none available)"

    prompt = f"""Split this tutorial/problem sheet into its individual questions, and tag each one with the topics it tests.

RULES FOR SPLITTING:
- One entry per LEAF question. If Q3 has parts (a), (b), (c), that is THREE entries with labels "3(a)", "3(b)", "3(c)" and group "3" — not one entry for Q3.
- A question with no parts is one entry: label "5", group "5".
- "label" is exactly how the paper numbers it — copy its own scheme, e.g. "1.1", "Problem 2.3", "4(b)". "grp" is the parent number alone.
- "text" is the question as written, verbatim where possible. Include any code, data or formula the question depends on. If the part depends on a stem shared with its siblings ("Consider the array below..."), repeat the stem in each part so the question stands alone.
- "page" is the page number the question starts on, from the === PAGE n === markers.
- Skip anything that is not a question: cover pages, contents listings, instructions, learning outcomes, "submit by Friday", mark schemes.
- Keep the paper's order.

THIS PAPER MAY CONTAIN THE SOLUTIONS INLINE, right after each question — look for "Solution", "Answer", "Ans:", "Model answer" or a worked derivation following the question.
- If it does, "text" MUST STOP where the solution begins. NEVER include any part of the solution, the final answer, or the working in "text". A student reads "text" to attempt the question; leaking the answer into it destroys the only thing this is for.
- Set "solution_page" to the page the solution starts on. Omit it if this paper has no solutions.
- The question and its solution often share a page. That is fine — report the page each starts on.

RULES FOR TAGGING:
- Choose topic ids ONLY from this list of the student's own note topics. Never invent an id.
- 1 to 3 ids per question, most relevant first. If nothing genuinely fits, use an empty list — a wrong tag is worse than no tag, because it will surface this question when they are revising something else.

<topics>
{topic_list}
</topics>

<tutorial>
{body}
</tutorial>

OUTPUT FORMAT:
Respond with ONLY a JSON array. No markdown fences, no preamble:
[{{"label": "3(a)", "grp": "3", "text": "<the question, WITHOUT its solution>", "page": 2, "solution_page": 3, "topic_ids": [91]}}]
"""
    result = call_for_json(prompt, max_tokens=8000, purpose="tutorial split")
    return result if isinstance(result, list) else result.get("questions", [])


def map_answer_pages(answer_pdf_id, labels):
    """Find which page of the ANSWER paper each question's answer starts on.

    Deliberately a LOOK-UP, not an extraction: the answers are shown by opening
    the answer PDF at the right page, so worked solutions keep their diagrams,
    equations and handwriting. Nothing is rewritten, so nothing can be
    rewritten wrongly. Returns {label: page}.
    """
    pages = get_pdf_pages(answer_pdf_id)
    if not pages:
        raise ValueError("No stored page text for the answer paper")
    # first ~600 chars of each page is plenty to spot "Question 3(a)" headings
    index = "\n".join(f"=== PAGE {p['page_number']} ===\n{(p['text'] or '')[:600]}"
                      for p in pages)[:40_000]

    prompt = f"""Below is a page-by-page index of an ANSWER paper. For each question label listed, say which page its answer STARTS on.

Question labels to locate:
{", ".join(labels)}

Rules:
- Use the === PAGE n === markers for the page number.
- Match the paper's own numbering, allowing for formatting differences: "3(a)", "3a", "Q3 (a)" and "Question 3, part a" are the same label.
- If a label's answer genuinely cannot be found, omit it. Do not guess a page.

<answer_paper_index>
{index}
</answer_paper_index>

OUTPUT FORMAT:
Respond with ONLY a JSON object mapping label to page number. No markdown fences, no preamble:
{{"3(a)": 2, "3(b)": 3}}
"""
    result = call_for_json(prompt, fast=True, max_tokens=2000, purpose="answer page map")
    return result if isinstance(result, dict) else {}


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
