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
    return call_for_json(prompt, max_tokens=4000)


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

Rules:
- One fact per card. If a sentence in the source uses 'and', 'or', or lists items, those items must become separate cards. For example: 'open addressing uses linear probing or quadratic probing' should produce THREE cards (one on open addressing, one on linear probing, one on quadratic probing), not one bundled card.
- You may paraphrase the source when writing the question and answer to make them clearer and more concise, but the meaning must be fully preserved.
- Questions must be unambiguous with a single correct answer directly supported by the verbatim text. No opinion-based or open-ended questions, and none that require synthesizing multiple concepts.
- Do not create questions whose answers are lists or sets of items — make one card per item instead.
- For code-related cards, test concepts over derivable facts: ask what the code is for or how it works, not what its output is.
- Answers should be 1 to 3 sentences: long enough to include reasoning, short enough to recall.
- Mix factual recall questions ('what...') with 'why' questions that probe understanding.

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
    return call_for_json(prompt, max_tokens=4000)


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
    return call_for_json(prompt, max_tokens=2000)


def _course_name(course_id):
    for course in get_courses():
        if course["id"] == course_id:
            return course["name"]
    return "Unknown"
