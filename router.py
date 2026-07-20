"""Three-layer router: pin fast-path → keyword heuristics → Haiku classifier.
Cheapest first; mid-session messages never leave the pinned agent (an answer
attempt must never be re-routed)."""

import re
from llm_utils import complete_text

AGENT_NAMES = {"ingestion", "review", "organizer", "planner"}

# words that let a message escape a pinned session
_ESCAPE = re.compile(
    r"\b(end|stop|quit|exit|finish|switch|cancel)\b.*\b(session|review|cram|quiz)\b"
    r"|\b(end|exit) (cram|review)\b|\bdashboard\b|\bingest\b",
    re.IGNORECASE,
)

_REVIEW_KW = re.compile(r"\b(review|due|cram|quiz|test me|revise)\b", re.IGNORECASE)
_PLANNER_KW = re.compile(
    r"\b(progress|complet(e|ion)|how am i doing|study log|studied|deadline|"
    r"what should i study|upcoming|decay|mastery|streak|stats|"
    r"plan|schedule)\b", re.IGNORECASE)
_INGEST_KW = re.compile(
    r"\.pdf\b|\b(ingest|upload|import|make cards from|extract|new notes|add notes)\b",
    re.IGNORECASE)
_ORGANIZER_KW = re.compile(r"\b(rename|reorganize|merge topics|move card)\b", re.IGNORECASE)


def route(user_text, pinned_agent=None, session_active=False, strict_pin=True):
    """Return the agent name that should handle this message.

    strict_pin=True (review sessions): any message that isn't an explicit
    escape stays pinned — a mid-quiz answer attempt can look like anything.
    strict_pin=False (ingestion approval flow): clear requests for another
    specialist may also escape."""
    # 1. pin fast-path: stay glued to an active session unless escaping
    if session_active and pinned_agent:
        if _ESCAPE.search(user_text):
            pass  # fall through to fresh routing
        elif strict_pin:
            return pinned_agent
        elif not (_REVIEW_KW.search(user_text) or _PLANNER_KW.search(user_text)
                  or _ORGANIZER_KW.search(user_text)):
            return pinned_agent

    # 2. keyword heuristics for unambiguous cases
    if _INGEST_KW.search(user_text):
        return "ingestion"
    if _REVIEW_KW.search(user_text):
        return "review"
    if _PLANNER_KW.search(user_text):
        return "planner"

    # 3. Haiku classifier
    return _classify(user_text, pinned_agent)


def _classify(user_text, pinned_agent):
    prompt = f"""Classify which specialist should handle this message in a flashcard study app. Answer with ONE word from: ingestion, review, organizer, planner, stay.

- ingestion: adding new study material (PDFs, notes) or generating flashcards from it
- review: doing a review/cram/quiz session on existing cards
- organizer: browsing/editing/deleting courses, documents, topics, cards; questions answered from saved notes
- planner: progress, completion %, what to study next, study history
- stay: continuation of the current conversation thread{f" (currently with: {pinned_agent})" if pinned_agent else " (no current thread — do not answer stay)"}

Examples:
"here are my biology notes" -> ingestion
"lets go through my due cards" -> review
"rename topic 3 to Backprop" -> organizer
"how far through the transformers pdf am I" -> planner
"what does my material say about hash collisions" -> organizer
"yes that looks good" -> stay

Message: "{user_text}"
Answer:"""
    try:
        raw, _ = complete_text(prompt, fast=True, max_tokens=10)
        label = raw.strip().lower()
        if label == "stay" and pinned_agent:
            return pinned_agent
        if label in AGENT_NAMES:
            return label
    except Exception:
        pass
    return pinned_agent or "organizer"
