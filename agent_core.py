"""Shared agent core — frameworks fork: turn execution runs on LangGraph's
prebuilt ReAct agent instead of the hand-rolled two-dialect tool loop (that
loop lives on in git history / the reference board). What stays OURS:
TOOL_HANDLERS, the id-validation guardrail, the specialists' prompts/tool
subsets, and the router/orchestrator pinning above this module."""

import json
import types
from datetime import date
from pydantic import create_model
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent
from llm_utils import chat_model
from tools import TOOL_SCHEMAS
from pdf_ingest import read_pdf, create_text_source, propose_topics
from generation import extract_topic_concepts, generate_cards_for_topic, generate_pretest
from grading import grade_answer
from search import search_notes
import mastery
import planning
import stats as stats_module
from database import (
    init_db,
    create_course, get_courses, delete_course,
    get_pdfs, get_pdf, delete_pdf,
    save_topics, get_topics, update_topic,
    save_concepts, get_note, delete_note,
    insert_card, get_cards, get_due_cards, review_card, undo_review,
    update_card, delete_card,
    insert_insight, get_insights_for_card, delete_insight,
    start_session, end_session, get_study_log, get_upcoming_reviews,
    get_mastery_inputs, save_study_plan, get_study_plan, set_exam_date,
)

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
    "review_card":      lambda card_id, quality: (lambda r:
        f"interval {r['old_interval']}d → {r['new_interval']}d · next {r['next_review']}")(review_card(card_id, quality)),
    "undo_review":      lambda card_id: (lambda p:
        f"Review undone. Card restored to interval {p['interval_days']}d, next review {p['next_review'][:10]}.")(undo_review(card_id)),
    "generate_pretest": generate_pretest,
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
    "propose_study_plan":  lambda days=7, minutes_per_day=60, course_id=None:
        planning.propose_plan(days=days, minutes_per_day=minutes_per_day, course_id=course_id),
    "save_study_plan":     lambda entries: f"Saved {save_study_plan(entries)} plan entries (future plan replaced).",
    "get_study_plan":      lambda start_date=None, end_date=None:
        _counted("plan entries", get_study_plan(start_date, end_date)),
    "get_study_stats":     lambda: stats_module.compute_stats(),
    "set_exam_date":       lambda course_id, date=None:
        (set_exam_date(course_id, date), f"Exam date {'set to ' + date if date else 'cleared'} for course {course_id}.")[1],
    "get_upcoming_reviews": lambda days=7: _counted("topics with upcoming reviews", get_upcoming_reviews(days)),
    "get_study_log":       lambda start_date=None, end_date=None, course_id=None:
        _counted("study sessions", get_study_log(start_date, end_date, course_id)),
}


_ID_PARAMS = {"course_id", "pdf_id", "topic_id", "card_id", "note_id", "insight_id", "session_id"}


def handle_tool(name, args):
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}"
    # id params must be integers — a filename/title passed as an id silently
    # matches nothing in SQL, which reads as "no cards due" to the model
    for key, value in list(args.items()):
        if key in _ID_PARAMS and value is not None and not isinstance(value, int):
            if isinstance(value, str) and value.isdigit():
                args[key] = int(value)
            else:
                return (f"Error: {key} must be an integer id, got {value!r}. "
                        f"Resolve names to ids first (get_courses / get_pdfs / get_topics).")
    try:
        return handler(**args)
    except Exception as e:
        # surface errors to the model so it can correct course instead of crashing the app
        return f"Error in {name}: {type(e).__name__}: {e}"


# per-turn callbacks reach the LangChain tool wrappers via module state.
# NOT thread-local: LangGraph's tool node may execute tools on worker threads,
# which would see an empty thread-local and silently drop the callbacks
# (observed: session pinning + grade cards went dead). Single-user app, one
# turn at a time — module state is correct here.
_turn_ctx = types.SimpleNamespace(log=None, on_tool=None)

_JSON_TYPES = {"string": str, "integer": int, "number": float,
               "boolean": bool, "array": list, "object": dict}


def _args_model(name, input_schema):
    """Pydantic args schema from our JSON tool schema (LangChain needs one)."""
    fields = {}
    required = set(input_schema.get("required", []))
    for prop, spec in input_schema.get("properties", {}).items():
        py_type = _JSON_TYPES.get(spec.get("type", "string"), str)
        fields[prop] = (py_type, ...) if prop in required else (py_type | None, None)
    return create_model(f"{name}_args", **fields)


def _make_lc_tool(name, schema):
    def call(**kwargs):
        # drop explicit Nones so handlers' defaults apply (LangChain fills
        # optional args with None)
        args = {k: v for k, v in kwargs.items() if v is not None}
        log = getattr(_turn_ctx, "log", None)
        on_tool = getattr(_turn_ctx, "on_tool", None)
        if log:
            log(f"[tool: {name}({args})]")
        result = handle_tool(name, args)   # guardrails (id validation) intact
        if log:
            log(f"[result: {str(result)[:200]}]")
        if on_tool:
            on_tool(name, args, result)
        return str(result)

    return StructuredTool.from_function(
        func=call, name=name, description=schema["description"],
        args_schema=_args_model(name, schema["input_schema"]))


_LC_TOOLS = None
_GRAPH_CACHE = {}


def _lc_tools():
    global _LC_TOOLS
    if _LC_TOOLS is None:
        _LC_TOOLS = {name: _make_lc_tool(name, schema)
                     for name, schema in TOOL_SCHEMAS.items()}
    return _LC_TOOLS


def _graph_for(agent):
    """One compiled LangGraph ReAct agent per specialist, rebuilt daily
    (the system prompt embeds today's date)."""
    key = (agent.name, date.today())
    if key not in _GRAPH_CACHE:
        tools = [_lc_tools()[name] for name in agent.tool_names]
        _GRAPH_CACHE[key] = create_react_agent(
            chat_model(), tools, prompt=agent.build_system_prompt())
    return _GRAPH_CACHE[key]


def run_turn(messages, agent, on_event=None, on_tool=None):
    """Run one assistant turn for the given AgentSpec through LangGraph.
    `messages` (LangChain message history) is mutated in place. Returns the
    final assistant text.

    on_event(str): logging callback (tool calls, results) — feeds the SSE
    status line. on_tool(name, input, result): structured callback with the
    RAW result — grade cards and orchestrator session-pinning hang off it."""
    def log(msg):
        if on_event:
            on_event(msg)

    _turn_ctx.log = log
    _turn_ctx.on_tool = on_tool
    try:
        graph = _graph_for(agent)
        log(f"[{agent.name} | langgraph]")
        # ingestion turns are legitimately long: a batch upload runs
        # read_pdf -> propose_topics -> save_topics per file (an 11-PDF batch
        # exhausted the default 60 and stranded pending stubs, 2026-07-26)
        limit = 240 if agent.name == "ingestion" else 60
        before = len(messages)
        result = graph.invoke({"messages": list(messages)},
                              config={"recursion_limit": limit})
        messages[:] = result["messages"]
        # spend tracking: LangChain carries usage on each AI message, and one
        # turn can be several model calls (tool loop) — log each of them
        from llm_utils import record_usage, MAIN_MODEL
        for msg in messages[before:]:
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                record_usage("assistant" if agent.name == "assistant" else f"agent ({agent.name})",
                             (getattr(msg, "response_metadata", {}) or {}).get("model_name") or MAIN_MODEL,
                             usage.get("input_tokens", 0), usage.get("output_tokens", 0))
        final = messages[-1]
        return final.content if isinstance(final.content, str) else str(final.content)
    finally:
        _turn_ctx.log = None
        _turn_ctx.on_tool = None
