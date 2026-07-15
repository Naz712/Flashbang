"""Shared agent core. Imported by both agent.py (terminal) and app.py (Streamlit).
Holds the tool dispatcher, the system prompt, and run_turn() — the inner loop that
keeps calling Claude until it stops requesting tools."""

from dotenv import load_dotenv
from pdf_ingest import extract_text_from_pdf_vision
from search import search_notes
import anthropic
from datetime import datetime
from generation import extract_concepts, generate_cards
from tools import tools
from database import (
    init_db,
    insert_event, get_events, delete_event,
    save_concepts, update_event, delete_note,
    insert_card, get_due_cards, review_card, delete_card, update_card, get_cards,
    insert_insight, get_insights_for_card, delete_insight, get_note,
)
from grading import grade_answer

load_dotenv()
client = anthropic.Anthropic()


def generate_cards_for_session(subject, topic, concepts, note_ids, per_concept_cap=5, total_cap=80):
    all_cards = []
    running_total = 0
    for concept, note_id in zip(concepts, note_ids):
        if running_total >= total_cap:
            break
        cap_for_this_call = min(per_concept_cap, total_cap - running_total)
        cards = generate_cards(subject, topic, [concept], cap_for_this_call)
        for card in cards:
            card["notes_id"] = note_id
        all_cards.extend(cards)
        running_total += len(cards)
    return all_cards


def bulk_insert_cards(cards):
    card_ids = []
    for card in cards:
        card_id = insert_card(**card)
        card_ids.append(card_id)
    return card_ids


def handle_tool(name, args):
    if name == "insert_event":
        insert_event(**args)
        return "Event inserted successfully."
    elif name == "get_events":
        events = get_events(**args)
        return str(events) if events else "No events found in that range."
    elif name == "delete_event":
        delete_event(**args)
        return "Event deleted successfully."
    elif name == "update_event":
        update_event(**args)
        return "Event updated successfully."
    elif name == "insert_card":
        card_id = insert_card(**args)
        return f"Card created (id: {card_id})."
    elif name == "get_due_cards":
        cards = get_due_cards()
        # Hand the model the count from len() — don't make it tally a long list.
        return f"{len(cards)} cards due:\n{cards}" if cards else "No cards due for review."
    elif name == "review_card":
        new_interval = review_card(**args)
        return f"Card reviewed. Next review in {new_interval} day(s)."
    elif name == "delete_card":
        delete_card(**args)
        return "Card deleted successfully."
    elif name == "update_card":
        update_card(**args)
        return "Card updated successfully."
    elif name == "get_cards":
        cards = get_cards(**args)
        # Prefix with the len() count so the model states the right number (it
        # otherwise miscounts long lists — e.g. "Card 1 of 37" vs "36 cards").
        return f"{len(cards)} cards:\n{cards}" if cards else "No cards found."
    elif name == "grade_answer":
        # Return the raw dict ({"quality", "feedback"}). run_turn str()-ifies it for
        # the model's tool_result, while on_tool gets the structured dict so the
        # Streamlit front-end can render a formatted grade card.
        return grade_answer(**args)
    elif name == "insert_insight":
        insight_id = insert_insight(**args)
        return f"Insight saved (id: {insight_id}) to card {args['card_id']}."
    elif name == "get_insights_for_card":
        insights = get_insights_for_card(**args)
        return str(insights) if insights else "No insights found for this card."
    elif name == "delete_insight":
        delete_insight(**args)
        return "Insight deleted successfully."
    elif name == "extract_concepts":
        result = extract_concepts(**args)
        return str(result)
    elif name == "save_concepts":
        note_ids = save_concepts(**args)
        return str(note_ids)
    elif name == "generate_cards_for_session":
        cards = generate_cards_for_session(**args)
        return str(cards)
    elif name == "bulk_insert_cards":
        card_ids = bulk_insert_cards(**args)
        return f"Inserted {len(card_ids)} cards (ids: {card_ids})."
    elif name == "extract_text_from_pdf_vision":
        text = extract_text_from_pdf_vision(**args)
        return text
    elif name == "delete_note":
        delete_note(**args)
        return "Note deleted successfully."
    elif name == "get_note":
        note = get_note(**args)
        return str(note) if note else "Note not found."
    elif name == "search_notes":
        results = search_notes(**args, min_score=0.3)
        if not results:
            return "No relevant notes found in the user's study material."
        return "\n\n".join(
            f"[note {note[0]} | {note[1]} / {note[2]} | {note[3]} | sim {score:.2f}]\n{note[4]}"
            for score, note in results
        )
    else:
        return f"Unknown tool: {name}"


system_prompt = f"""You are a helpful personal assistant for managing a calendar, flashcards, and study notes. Today's date is {datetime.now().strftime('%Y-%m-%d')}.

Use the provided tools to carry out the user's requests. After completing an action, briefly confirm what you did.

## Calendar
- Convert relative dates ('tomorrow', 'next Monday') to ISO 8601 datetimes before calling any tool.
- get_events requires full datetimes, not bare dates. For a single day, use T00:00 as the start and T23:59 as the end.

## Reviewing flashcards
When the user wants to review, call get_due_cards first. Then, for each card:
1. Show ONLY the question. Never reveal the answer or give hints.
2. Wait for the user's attempt.
3. Call grade_answer with the question, the card's stored correct_answer, and the user's attempt.
4. Show the returned feedback, then call review_card with the card's id and the quality score from grade_answer.
5. Move to the next card.

## Cram mode
If the user asks to 'cram' (or 'cram sesh', etc.), call get_cards for the requested subject or topic, shuffle the cards, and quiz through all of them using the same show -> attempt -> grade -> feedback loop as review. During cram, do NOT call review_card — this is quizzing, not spaced repetition. Go through each card once. Cram ends when every card has been quizzed once, or when the user types 'end cram' or 'exit cram'.

## Session discipline (applies to both review and cram)
- Run ONE session at a time. If the user asks for both a cram and a review, do them strictly in sequence: fully finish the first (every card quizzed once) before starting the second. Never blend them or run them at once.
- Once a session is underway and you have just shown a card's question, treat the user's NEXT message as their answer attempt for that card. Immediately call grade_answer and give feedback, then show the next card. Do NOT re-introduce the session, re-shuffle, or restate the plan mid-session.
- State counts from the tool result's count line (e.g. "N cards"), not from your own tally of the list — they must match exactly throughout the session.

## Insights
- Never show insights automatically. Fetch them only when the user explicitly asks ('show insights', 'what insights do I have', 'any notes for this card').
- Save an insight only on an explicit cue ('save that', 'remember this', 'note that', 'add a note'). When cued, do NOT save immediately: first write a proposed 1-2 sentence summary, show it, and ask whether to save, edit, or skip. Only call insert_insight after the user confirms.
- Use the most recently shown card as card_id, and the concise summary as content.
- To delete, use the id from the most recent insert or list. If the id is ambiguous, ask the user to specify before calling delete_insight.

## Answering questions from notes
For any conceptual or factual question that isn't about managing the calendar or flashcards, call search_notes BEFORE answering.
- If relevant chunks come back, ground your answer in them and name the subject/topic they came from. You may add a brief clarification from your own knowledge, kept clearly separate from what the notes say.
- If nothing clears the relevance threshold, tell the user it isn't in their notes, then give a general answer only if they'd like one.

## Notes-to-cards flow
1. Trigger phrases: 'make cards from this', 'extract these notes', 'card workflow'. If the user gives a PDF path, call extract_text_from_pdf_vision first; if they paste text directly, skip that. Then call extract_concepts on the text.
2. Show the extracted concepts and wait for explicit approval. If the user requests changes (drop, rename, edit), update the list yourself and re-show. Do NOT call save_concepts yet.
3. Once approved, call save_concepts with the final subject, topic, and concepts list, and capture the returned note_ids.
4. Call generate_cards_for_session with subject, topic, concepts, and note_ids.
5. Show the full batch of generated cards and wait for approval. The user may approve all, drop cards by number, or request regeneration.
6. Pass the approved list to bulk_insert_cards (dropping any rejected cards first). Do not loop insert_card manually — bulk_insert_cards handles the loop and preserves notes_id.
"""


def run_turn(messages, on_event=None, on_tool=None):
    """Run one assistant turn. `messages` (the API history) is mutated in place:
    the assistant reply and any tool_result messages are appended. Keeps calling
    Claude until it stops requesting tools, then returns the final assistant text.

    on_event(str): optional callback for logging (tool calls, stop reasons).
    The terminal passes `print`; Streamlit collects them into an expander.
    on_tool(name, input, result): optional structured callback fired for every tool
    call with the RAW (un-stringified) result. Streamlit uses this to render a
    formatted grade card from grade_answer's dict; the terminal ignores it.
    """
    def log(msg):
        if on_event:
            on_event(msg)

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )
        log(f"[stop_reason: {response.stop_reason}]")
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

        # end_turn (or max_tokens, etc.) — return whatever text was produced
        return "".join(b.text for b in response.content if b.type == "text")
