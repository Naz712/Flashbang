"""Shared agent core. run_turn() drives one assistant turn for whichever
specialist agent the orchestrator picked: it keeps calling Claude with that
agent's system prompt + tool subset until no more tools are requested.
Tool dispatch is a registry (TOOL_HANDLERS) instead of an if/elif chain."""

from llm_utils import client
from tools import tools_for
from pdf_ingest import read_pdf, create_text_source, propose_topics
from generation import extract_topic_concepts, generate_cards_for_topic
from grading import grade_answer
from search import search_notes
import mastery
from database import (
    init_db,
    create_course, get_courses, delete_course,
    get_pdfs, get_pdf, delete_pdf,
    save_topics, get_topics, update_topic,
    save_concepts, get_note, delete_note,
    insert_card, get_cards, get_due_cards, review_card, update_card, delete_card,
    insert_insight, get_insights_for_card, delete_insight,
    start_session, end_session, get_study_log, get_upcoming_reviews,
    get_mastery_inputs,
)

MODEL = "claude-sonnet-4-5"


def _rows(rows):
    return [dict(r) for r in rows]


def _counted(label, rows):
    # Prefix with the len() count so the model states the right number (it
    # otherwise miscounts long lists — e.g. "Card 1 of 37" vs "36 cards").
    items = _rows(rows)
    return f"{len(items)} {label}:\n{items}" if items else f"No {label} found."


def _bulk_insert_cards(cards):
    card_ids = []
    for card in cards:
        card_id = insert_card(topic_id=card["topic_id"], question=card["question"],
                              answer=card["answer"], note_id=card.get("note_id"))
        card_ids.append(card_id)
    return f"Inserted {len(card_ids)} cards (ids: {card_ids})."


def _search_notes(query, top_k=3, course_id=None):
    results = search_notes(query, top_k=top_k, min_score=0.3, course_id=course_id)
    if not results:
        return "No relevant notes found in the user's study material."
    return "\n\n".join(
        f"[note {row['id']} | {row['course_name']} / {row['pdf_filename']} / "
        f"{row['topic_title']} | sim {score:.2f}]\n{row['content']}"
        for score, row in results
    )


def _progress_report(pdf_id=None, course_id=None):
    if pdf_id:
        pdf_ids = [pdf_id]
    elif course_id:
        pdf_ids = [p["id"] for p in get_pdfs(course_id)]
    else:
        pdf_ids = [p["id"] for p in get_pdfs()]
    if not pdf_ids:
        return "No ingested documents found."
    reports = []
    for pid in pdf_ids:
        pdf = get_pdf(pid)
        topics, cards = get_mastery_inputs(pid)
        reports.append(mastery.build_pdf_report(pdf, topics, cards))
    return reports


TOOL_HANDLERS = {
    # courses & library
    "create_course":    lambda name: f"Course created (id: {create_course(name)}).",
    "get_courses":      lambda: _counted("courses", get_courses()),
    "delete_course":    lambda course_id: (delete_course(course_id), "Course and all its contents deleted.")[1],
    "get_pdfs":         lambda course_id=None: _counted("documents", get_pdfs(course_id)),
    "delete_pdf":       lambda pdf_id: (delete_pdf(pdf_id), "Document and all its contents deleted.")[1],

    # ingestion
    "read_pdf":                 read_pdf,
    "create_text_source":       create_text_source,
    "propose_topics":           propose_topics,
    "save_topics":              lambda pdf_id, topics: f"Saved {len(topics)} topics (ids: {save_topics(pdf_id, topics)}). Document marked ready.",
    "get_topics":               lambda pdf_id=None, course_id=None: _counted("topics", get_topics(pdf_id, course_id)),
    "update_topic":             lambda **kw: (update_topic(**kw), "Topic updated.")[1],
    "extract_topic_concepts":   extract_topic_concepts,
    "save_topic_concepts":      lambda topic_id, concepts: f"Saved {len(concepts)} concepts. note_ids (same order): {save_concepts(topic_id, concepts)}",
    "generate_cards_for_topic": generate_cards_for_topic,
    "bulk_insert_cards":        _bulk_insert_cards,

    # cards & review
    "insert_card":      lambda topic_id, question, answer: f"Card created (id: {insert_card(topic_id, question, answer)}).",
    "get_cards":        lambda course_id=None, pdf_id=None, topic_id=None: _counted("cards", get_cards(course_id, pdf_id, topic_id)),
    "get_due_cards":    lambda course_id=None, pdf_id=None, topic_id=None: _counted("cards due", get_due_cards(course_id, pdf_id, topic_id)),
    "review_card":      lambda card_id, quality: f"Card reviewed. Next review in {review_card(card_id, quality)} day(s).",
    "update_card":      lambda **kw: (update_card(**kw), "Card updated.")[1],
    "delete_card":      lambda card_id: (delete_card(card_id), "Card deleted.")[1],
    "grade_answer":     grade_answer,   # returns raw dict; run_turn str()s it, on_tool gets the dict

    # insights
    "insert_insight":        lambda card_id, content: f"Insight saved (id: {insert_insight(card_id, content)}) to card {card_id}.",
    "get_insights_for_card": lambda card_id: _counted("insights", get_insights_for_card(card_id)),
    "delete_insight":        lambda insight_id: (delete_insight(insight_id), "Insight deleted.")[1],

    # notes
    "get_note":     lambda note_id: (lambda row: str(dict(row)) if row else "Note not found.")(get_note(note_id)),
    "delete_note":  lambda note_id: (delete_note(note_id), "Note deleted.")[1],
    "search_notes": _search_notes,

    # sessions & progress
    "start_study_session": lambda kind, course_id=None, pdf_id=None, topic_ids=None:
        {"session_id": start_session(kind, course_id, pdf_id, topic_ids), "kind": kind},
    "end_study_session":   lambda session_id, cards_reviewed=None, summary=None:
        end_session(session_id, cards_reviewed, summary),
    "get_progress_report": _progress_report,
    "get_upcoming_reviews": lambda days=7: _counted("topics with upcoming reviews", get_upcoming_reviews(days)),
    "get_study_log":       lambda start_date=None, end_date=None, course_id=None:
        _counted("study sessions", get_study_log(start_date, end_date, course_id)),
}


def handle_tool(name, args):
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}"
    try:
        return handler(**args)
    except Exception as e:
        # surface errors to the model so it can correct course instead of crashing the app
        return f"Error in {name}: {type(e).__name__}: {e}"


def run_turn(messages, agent, on_event=None, on_tool=None):
    """Run one assistant turn for the given AgentSpec. `messages` (the API
    history) is mutated in place. Returns the final assistant text.

    on_event(str): optional logging callback (tool calls, stop reasons).
    on_tool(name, input, result): optional structured callback with the RAW
    (un-stringified) result — Streamlit renders grade_answer dicts from this,
    and the orchestrator watches it for session pinning."""
    def log(msg):
        if on_event:
            on_event(msg)

    system_prompt = agent.build_system_prompt()
    tools = tools_for(agent.tool_names)

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )
        log(f"[{agent.name} | stop_reason: {response.stop_reason}]")
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    log(f"[tool: {block.name}({block.input})]")
                    result = handle_tool(block.name, block.input)
                    log(f"[result: {str(result)[:200]}]")
                    if on_tool:
                        on_tool(block.name, block.input, result)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        return "".join(b.text for b in response.content if b.type == "text")
