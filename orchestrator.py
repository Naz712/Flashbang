"""Conversation orchestrator, shared by the terminal REPL and Streamlit.
Holds one message history for the whole conversation; per turn the router
picks a specialist and run_turn swaps in its system prompt + tool subset.

Session pinning rides on the study-log tools: start_study_session pins the
review agent (and opens the log row), end_study_session unpins (and closes
it). Ingestion is soft-pinned between read_pdf and save_topics so its
multi-step approval flow isn't interrupted. Log and pin are the same event,
so neither can drift."""

from agent_core import run_turn
from agents import AGENTS
from router import route
from database import init_db


class Orchestrator:
    def __init__(self):
        init_db()
        self.messages = []
        self.pinned = None
        self.session_active = False
        self.strict_pin = True
        self.active_session_id = None
        self.last_agent = None

    def handle(self, user_text, on_event=None, on_tool=None, force_agent=None):
        if force_agent in AGENTS:
            agent_name = force_agent   # slash command — intent is explicit, skip routing
        else:
            agent_name = route(user_text, self.pinned, self.session_active, self.strict_pin)
        agent = AGENTS[agent_name]
        self.last_agent = agent_name
        if on_event:
            on_event(f"[router -> {agent_name}{' (forced)' if force_agent in AGENTS else ''}]")

        self.messages.append({"role": "user", "content": user_text})
        return run_turn(self.messages, agent,
                        on_event=on_event,
                        on_tool=self._wrap_on_tool(on_tool))

    def _wrap_on_tool(self, downstream):
        def observer(name, args, result):
            if name == "start_study_session" and isinstance(result, dict):
                self.pinned = "review"
                self.session_active = True
                self.strict_pin = True   # answer attempts can look like anything
                self.active_session_id = result.get("session_id")
            elif name == "end_study_session":
                self.pinned = None
                self.session_active = False
                self.active_session_id = None
            elif name in ("read_pdf", "create_text_source") and isinstance(result, dict):
                # soft-pin ingestion through the propose/approve/generate flow
                self.pinned = "ingestion"
                self.session_active = True
                self.strict_pin = False  # clear asks for review/planner may escape
            elif name == "bulk_insert_cards":
                # cards landed — approval flow done (re-entry is keyword-routed)
                self.pinned = None
                self.session_active = False
            elif name == "propose_study_plan":
                # soft-pin planner so "looks good, save it" reaches save_study_plan
                self.pinned = "planner"
                self.session_active = True
                self.strict_pin = False
            elif name == "save_study_plan":
                self.pinned = None
                self.session_active = False
            if downstream:
                downstream(name, args, result)
        return observer
