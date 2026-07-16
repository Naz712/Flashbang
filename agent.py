"""Terminal front-end. The agent logic lives in orchestrator.py (routing +
specialists) so the Streamlit dashboard can share it. This file is just the
read-eval-print loop."""

from orchestrator import Orchestrator

orchestrator = Orchestrator()

print("Flashbang ready. Type 'quit' to exit.\n")

while True:
    user_input = input("You: ").strip()
    if user_input.lower() in {"quit", "exit"}:
        break
    if not user_input:
        continue

    text = orchestrator.handle(user_input, on_event=print)  # on_event=print keeps debug logs
    if text:
        print(f"Claude: {text}\n")
