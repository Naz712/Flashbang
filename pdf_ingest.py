"""PDF ingestion pipeline.

Stage 1: extract_pages — pypdf per page (free, local). Pages with too little
         text (scanned slides, diagram-only pages) are re-extracted in batches
         via Claude vision on an in-memory sub-PDF. No silent truncation: a
         batch that hits max_tokens is split in half and retried.
Stage 2: segment_topics — one Claude call over page-marked text returns real
         content topics with page ranges and per-topic time estimates. Long
         PDFs are chunked on page boundaries and merged mechanically.

read_pdf() / create_text_source() are the agent-facing entry points; both
persist pages to the pdf_pages table so extraction cost is paid once.
"""

import base64
import io
import os
from pypdf import PdfReader, PdfWriter
from llm_utils import (PROVIDER, MAIN_MODEL, anthropic_client, openai_client,
                       call_for_json, record_usage)
from database import create_pdf, save_pdf_pages, get_pdf_pages, get_pdf

SPARSE_THRESHOLD = 200   # chars; below this a page is probably scanned/diagram-only
VISION_BATCH_SIZE = 8    # pages per vision call
SEGMENT_CHUNK_CHARS = 100_000  # ~25k tokens of page text per segmentation call


# ---------------------------------------------------------------- stage 1: pages

def extract_pages(pdf_path):
    """pypdf first pass. Returns [{'page_number', 'text', 'extractor'}], 1-based."""
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        pages.append({"page_number": i, "text": text, "extractor": "pypdf"})
    return pages


def _build_sub_pdf(pdf_path, page_numbers):
    """In-memory PDF containing only the given (1-based) pages, base64-encoded."""
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    for n in page_numbers:
        writer.add_page(reader.pages[n - 1])
    buffer = io.BytesIO()
    writer.write(buffer)
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")


def _vision_prompt(page_numbers):
    listed = ", ".join(str(n) for n in page_numbers)
    return f"""This PDF contains {len(page_numbers)} pages. In the original document they are pages {listed}, in that order.

Extract all text content from every page, in reading order.
- Transcribe equations as LaTeX, unaltered, including any explanation attached to the math.
- Transcribe tables as Markdown tables.
- Transcribe code exactly as written, including any explanation attached to it.
- For images and diagrams, interpret what they convey rather than describing them decoratively.
- Begin each page's content with a marker line: === PAGE <original page number> === (using the original page numbers listed above, in order).
- If a page is blank or has no meaningful content, still output its marker followed by [EMPTY].

Return only the extracted content with the page markers. No preamble, commentary, or explanation."""


def vision_extract_pages(pdf_path, page_numbers):
    """Extract the given pages via Claude vision. Returns {page_number: text}.
    Recursively splits a batch when the response is truncated."""
    if not page_numbers:
        return {}
    results = {}
    for start in range(0, len(page_numbers), VISION_BATCH_SIZE):
        batch = page_numbers[start:start + VISION_BATCH_SIZE]
        results.update(_vision_extract_batch(pdf_path, batch))
    return results


def _vision_extract_batch(pdf_path, batch):
    pdf_data = _build_sub_pdf(pdf_path, batch)

    if PROVIDER == "openai":
        response = openai_client().chat.completions.create(
            model=MAIN_MODEL,
            max_completion_tokens=8000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "file",
                     "file": {"filename": "pages.pdf",
                              "file_data": f"data:application/pdf;base64,{pdf_data}"}},
                    {"type": "text", "text": _vision_prompt(batch)},
                ],
            }],
        )
        usage = getattr(response, "usage", None)
        record_usage("vision extraction", MAIN_MODEL,
                     getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0))
        truncated = response.choices[0].finish_reason == "length"
        text = response.choices[0].message.content or ""
    else:
        response = anthropic_client().messages.create(
            model=MAIN_MODEL,
            max_tokens=8000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "document",
                     "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data}},
                    {"type": "text", "text": _vision_prompt(batch)},
                ],
            }],
        )
        usage = getattr(response, "usage", None)
        record_usage("vision extraction", MAIN_MODEL,
                     getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0))
        truncated = response.stop_reason == "max_tokens"
        text = response.content[0].text

    if truncated:
        if len(batch) == 1:
            raise RuntimeError(f"Vision extraction of single page {batch[0]} exceeded 8000 tokens")
        mid = len(batch) // 2
        results = _vision_extract_batch(pdf_path, batch[:mid])
        results.update(_vision_extract_batch(pdf_path, batch[mid:]))
        return results
    return _parse_page_markers(text, batch)


def _parse_page_markers(text, expected_pages):
    """Split '=== PAGE n ===' delimited output back into {page_number: text}."""
    results = {}
    current_page = None
    current_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("=== PAGE") and stripped.endswith("==="):
            if current_page is not None:
                results[current_page] = "\n".join(current_lines).strip()
            try:
                current_page = int(stripped.replace("=== PAGE", "").replace("===", "").strip())
            except ValueError:
                current_page = None
            current_lines = []
        elif current_page is not None:
            current_lines.append(line)
    if current_page is not None:
        results[current_page] = "\n".join(current_lines).strip()
    # only keep pages we asked for; drop [EMPTY] placeholders
    return {n: t for n, t in results.items()
            if n in set(expected_pages) and t and t != "[EMPTY]"}


def pages_needing_vision(pages, force_vision=False):
    """Which pages to send to the vision model.

    Default: only pages whose local text extraction came back sparse — those
    are scanned or diagram-only. NOTE the known limit: a slide carrying a big
    diagram AND a paragraph of text passes the threshold, so its diagram is
    never read. force_vision=True is the escape hatch for decks like that —
    it reads every page as an image, at roughly $0.11 per 8 pages."""
    if force_vision:
        return [p["page_number"] for p in pages]
    return [p["page_number"] for p in pages if len(p["text"]) < SPARSE_THRESHOLD]


def read_pdf(pdf_path, course_id, force_vision=False):
    """Agent entry point: register the pdf, extract every page (pypdf + vision
    fallback for sparse pages), persist to pdf_pages. Returns ingestion stats."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pages = extract_pages(pdf_path)
    pdf_id = create_pdf(course_id, os.path.basename(pdf_path),
                        file_path=os.path.abspath(pdf_path), total_pages=len(pages))

    sparse = pages_needing_vision(pages, force_vision)
    if sparse:
        vision_texts = vision_extract_pages(pdf_path, sparse)
        for p in pages:
            if p["page_number"] in vision_texts:
                p["text"] = vision_texts[p["page_number"]]
                p["extractor"] = "vision"

    save_pdf_pages(pdf_id, pages)
    return {
        "pdf_id": pdf_id,
        "total_pages": len(pages),
        "vision_pages": sorted(set(sparse) & set(
            p["page_number"] for p in pages if p["extractor"] == "vision")),
        "status": "pending — call propose_topics next",
    }


def create_text_source(course_id, title, text):
    """Pasted-notes entry point: same pipeline as a pdf, one synthetic page."""
    pdf_id = create_pdf(course_id, title, source_type="text", total_pages=1)
    save_pdf_pages(pdf_id, [{"page_number": 1, "text": text, "extractor": "text"}])
    return {"pdf_id": pdf_id, "total_pages": 1, "status": "pending — call propose_topics next"}


# ---------------------------------------------------------------- stage 2: topics

def _segmentation_prompt(pages_text, course_name, page_range, carry_over=None):
    continuation = ""
    if carry_over:
        continuation = f"""
Note: the previous chunk of this document ended inside a topic titled "{carry_over['title']}" (started on page {carry_over['page_start']}). If the first pages of this chunk continue that same topic, your first topic must reuse that EXACT title so the chunks can be merged.
"""
    return f"""You are analyzing lecture/study material from the course "{course_name}" to split it into its actual content topics.

TASK:
Read the page-marked text below (pages {page_range[0]}–{page_range[1]}) and divide it into topics by CONTENT — what the material is actually about — not by arbitrary page counts. A topic is a coherent unit a student would study in one sitting: a concept, technique, or theme with its definitions, examples, and exercises.
{continuation}
For each topic estimate the study time in minutes: the time for a student seeing this material for the first time to read it carefully and understand it. Use this rubric:
- Baseline: ~2 minutes per sparse slide-style page, ~5 minutes per dense text page.
- Scale up for density of equations, proofs, or code (these need working through, not just reading): up to 2-3x.
- Scale down for title pages, section dividers, and administrative content.

Rules:
- Page ranges must be contiguous, non-overlapping, and together cover every page in this chunk.
- A topic must span at least 1 page; topics typically span 2-10 pages.
- Title pages / outlines / admin pages belong to the nearest real topic (usually the following one).
- Titles must be SHORT and instantly scannable — 2-4 words, max ~35 characters:
  - Use widely-known abbreviations (OOP, HOF, I/O, API, CNN, RNN, SVM, MLP, regex).
  - Drop filler: "Introduction to X" → "X Intro"; never "Understanding...", "Concepts of...",
    "Examples and Tutorials on...".
  - Specific beats generic: "Method Overriding & @Override", not "More Class Features".
- "summary" is 1-2 sentences on what the topic covers — the detail lives here, not in the title.
- "kind" separates studyable material from everything else:
  - "content": actual course material — concepts, techniques, worked examples, exercises.
  - "general": course admin and framing — schedules, assessment weightings, reading lists,
    lecturer/contact info, agenda/outline sections, "what we covered" recaps, homework
    instructions, closing/thank-you pages. These stay in the split (pages must be covered)
    but are flagged so no flashcards get made from them.
  - A MOSTLY-admin stretch is "general" even if it name-drops concepts; a real topic that
    merely opens with a title slide is still "content".

<pages>
{pages_text}
</pages>

OUTPUT FORMAT:
Respond with ONLY a JSON object in this exact format. No markdown code fences, no preamble:
{{
    "topics": [
        {{
            "title": "<string, short specific title, e.g. 'Self-Attention', 'OOP Inheritance'>",
            "summary": "<string, 1-2 sentences>",
            "page_start": <integer>,
            "page_end": <integer>,
            "est_minutes": <integer>,
            "kind": "<'content' or 'general'>"
        }}
    ]
}}
"""


def _normalize_ranges(topics, first_page, last_page):
    """Deterministically repair the model's page ranges: sorted, contiguous,
    non-overlapping, covering first_page..last_page. LLMs occasionally return
    overlapping or gapped ranges no matter what the prompt says."""
    topics = sorted(topics, key=lambda t: (t["page_start"], t["page_end"]))
    prev_end = first_page - 1
    for i, t in enumerate(topics):
        t["page_start"] = prev_end + 1
        end = max(t["page_end"], t["page_start"])
        if i == len(topics) - 1:
            end = max(end, last_page)   # last topic absorbs any trailing gap
        t["page_end"] = min(end, last_page)
        prev_end = t["page_end"]
    # drop topics squeezed past the end of the document (heavy overlap case)
    return [t for t in topics if t["page_start"] <= last_page]


def segment_topics(pdf_id, course_name):
    """Segment a pdf's stored pages into topics with time estimates.
    Chunks long documents on page boundaries; same-titled boundary topics are
    merged mechanically (page ranges extended, minutes summed)."""
    pages = get_pdf_pages(pdf_id)
    if not pages:
        raise ValueError(f"No stored pages for pdf {pdf_id} — call read_pdf first")

    # build chunks of whole pages under the char budget
    chunks = []
    current, current_len = [], 0
    for page in pages:
        page_block = f"=== PAGE {page['page_number']} ===\n{page['text']}"
        if current and current_len + len(page_block) > SEGMENT_CHUNK_CHARS:
            chunks.append(current)
            current, current_len = [], 0
        current.append(page)
        current_len += len(page_block)
    if current:
        chunks.append(current)

    all_topics = []
    carry_over = None
    for chunk in chunks:
        chunk_text = "\n\n".join(f"=== PAGE {p['page_number']} ===\n{p['text']}" for p in chunk)
        page_range = (chunk[0]["page_number"], chunk[-1]["page_number"])
        prompt = _segmentation_prompt(chunk_text, course_name, page_range, carry_over)
        result = call_for_json(prompt, max_tokens=4000, purpose="segmentation")
        topics = result["topics"]

        # merge a topic continued across the chunk boundary
        if (all_topics and topics
                and topics[0]["title"] == all_topics[-1]["title"]):
            all_topics[-1]["page_end"] = topics[0]["page_end"]
            all_topics[-1]["est_minutes"] += topics[0]["est_minutes"]
            topics = topics[1:]
        all_topics.extend(topics)
        if all_topics:
            carry_over = {"title": all_topics[-1]["title"],
                          "page_start": all_topics[-1]["page_start"]}

    return _normalize_ranges(all_topics, pages[0]["page_number"], pages[-1]["page_number"])


def propose_topics(pdf_id):
    """Agent entry point: segmentation + estimates for user review. Saves NOTHING —
    the agent shows the proposal and only save_topics persists it after approval."""
    pdf = get_pdf(pdf_id)
    if pdf is None:
        raise ValueError(f"No pdf with id {pdf_id}")
    from database import get_courses
    course_name = next((c["name"] for c in get_courses() if c["id"] == pdf["course_id"]), "Unknown")

    topics = segment_topics(pdf_id, course_name)
    total_minutes = sum(t["est_minutes"] for t in topics)
    return {
        "pdf_id": pdf_id,
        "topics": topics,
        "est_total_minutes": total_minutes,
        "est_total_hours": round(total_minutes / 60, 1),
    }
