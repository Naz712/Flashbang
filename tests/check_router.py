"""Router checks — pin fast-path and keyword layers only (no API needed;
Haiku layer is exercised implicitly in real use).
Run: .\\flashbang\\Scripts\\python.exe tests\\check_router.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router import route

# strict pin (review session): anything that isn't an escape stays pinned
assert route("the mitochondria is the powerhouse of the cell",
             pinned_agent="review", session_active=True, strict_pin=True) == "review"
assert route("hmm i think it's about O(n log n)?",
             pinned_agent="review", session_active=True, strict_pin=True) == "review"
# even planner-sounding words stay pinned under strict
assert route("was my progress on that one bad?",
             pinned_agent="review", session_active=True, strict_pin=True) == "review"
# "end review session" still goes to the review agent — it's the one that must
# call end_study_session to close the log
assert route("end review session please",
             pinned_agent="review", session_active=True, strict_pin=True) == "review"
# escape + clear other-agent intent leaves the session
assert route("stop this quiz, ingest my new lecture notes",
             pinned_agent="review", session_active=True, strict_pin=True) == "ingestion"

# soft pin (ingestion): approvals stay, clear review asks escape
assert route("yes those topics look good, save them",
             pinned_agent="ingestion", session_active=True, strict_pin=False) == "ingestion"
assert route("drop cards 3 and 7, keep the rest",
             pinned_agent="ingestion", session_active=True, strict_pin=False) == "ingestion"
assert route("actually let's review my due cards",
             pinned_agent="ingestion", session_active=True, strict_pin=False) == "review"

# keyword layer, no pin
assert route("ingest C:/notes/Lecture3_Transformer1.pdf") == "ingestion"
# review intent wins even when a .pdf filename is mentioned
assert route("Review my due cards in Lecture3_Transformer1.pdf") == "review"
assert route("make cards from these notes") == "ingestion"
assert route("quiz me on hashing") == "review"
assert route("let's cram biology") == "review"
assert route("how's my progress on the transformers pdf") == "planner"
assert route("what did I study last week? show the study log") == "planner"

print("check_router: ALL PASSED (keyword + pin layers)")
