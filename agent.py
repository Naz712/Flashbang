"""Terminal front-end. The agent logic now lives in agent_core.py so the
Streamlit dashboard can share it. This file is just the read-eval-print loop."""

from agent_core import run_turn

messages = []  # the running API conversation history

print("Calendar agent ready. Type 'quit' to exit.\n")

while True:
    user_input = input("You: ").strip()
    if user_input.lower() in {"quit", "exit"}:
        break
    if not user_input:
        continue

    messages.append({"role": "user", "content": user_input})
    text = run_turn(messages, on_event=print)  # on_event=print keeps your debug logs
    if text:
        print(f"Claude: {text}\n")
