from llm_utils import call_for_json


def grade_answer(question, correct_answer, user_answer, confidence=None):
    """Grade a recall attempt and return STRUCTURED feedback.

    The structure follows the feedback literature:
    - right/gap  -> task-level "how am I going" (Hattie & Timperley 2007),
                    specific and concise, no vague praise (Shute 2008)
    - the model answer is always shown by the app (correct-answer feedback
      outperforms right/wrong-only feedback)
    - why        -> elaborated feedback aids transfer, not just retention
    - hook       -> feed-forward: a cue for the NEXT retrieval attempt
    - calibration-> hypercorrection effect (Butterfield & Metcalfe 2001):
                    high-confidence errors are the most correctable and
                    deserve an explicit flag
    """
    confidence_line = (
        f'\nStated confidence before answering: "{confidence}"' if confidence else "")

    prompt = f"""You are grading a student's flashcard recall attempt.

Question: "{question}"
Stored correct answer: "{correct_answer}"
Student's attempt: "{user_answer}"{confidence_line}

Grade the attempt on a scale of 0 to 5:
0 = completely wrong, or unable to answer at all
1 = wrong, but the student understood the question and made a relevant attempt
2 = wrong, with a misconception that's relevant to the topic
3 = correct main idea, but vague or missing key terminology
4 = correct with most details, missing some minor specifics
5 = fully correct, all key ideas and details present

Grade meaning, not wording: do NOT penalize paraphrasing. If the attempt conveys the same facts in different words, it is correct.

Then produce structured feedback fields. WRITE LIKE A PATIENT TUTOR SITTING NEXT TO THEM, not like a marker filling a rubric:
- Plain, everyday words. Use a technical term only when that term is the thing being tested — and when you do, define it in a few words the first time.
- No hedging, no praise padding, no exam-report tone ("the candidate failed to...").
- Short sentences. Say the idea, then make it concrete.

- "right": what the attempt got correct, named specifically ("" if nothing was right). Never generic praise.
- "gap": what was missing or wrong, said kindly and plainly, AND what the right idea is ("" if fully correct). If they confused two things, name both and say which is which.
- "why": the TEACHING field — 1-2 sentences that make the idea click, and where it helps, ONE tiny concrete example or everyday analogy. Not a restatement of the answer; explain what's actually going on.
- "hook": a short memory cue for the next recall — a vivid association, contrast, or rule of thumb (max ~12 words).
- "calibration": ONLY if a stated confidence was given, one short note comparing confidence to performance. For a confident answer graded 0-2, flag it: confidently-held errors are the most correctable, but they come back without extra attention. For unsure-but-correct, note the recall was better than they felt. "" if no confidence stated.

Examples:

Question: "What is the difference between a list and a tuple in Python?"
Stored answer: "Lists are mutable, tuples are immutable. Lists use [], tuples use (). Tuples can be dict keys, lists cannot."

Attempt: "banana"
{{"quality": 0, "right": "", "gap": "Nothing to work with here — the question is about how lists and tuples differ: whether you can change them, how you write them, and where you can use them.", "why": "A list is like a shopping list you keep editing; a tuple is like a printed receipt — once it exists, it's fixed. That fixedness is the whole difference, and everything else follows from it.", "hook": "Tuple = printed receipt; list = shopping list.", "calibration": ""}}

Attempt: "Lists can be changed, tuples can't." (confidence: sure)
{{"quality": 3, "right": "The main idea — lists can be changed, tuples can't.", "gap": "Two things still missing: how you write them (lists use [], tuples use ()), and that only tuples can be used as dictionary keys.", "why": "Because a tuple can never change, Python can compute a fingerprint for it once and trust it forever — and that's exactly what a dictionary needs from a key. A list could change after you filed it, so the dictionary would lose track of it.", "hook": "Can't change → safe fingerprint → usable as a key.", "calibration": "You said sure and were mostly right — well calibrated; just chase the last details."}}

Attempt: "Lists are changeable with square brackets; tuples are fixed, use parentheses, and can be dict keys." (confidence: unsure)
{{"quality": 5, "right": "All three parts — changeability, the brackets, and dict keys.", "gap": "", "why": "The three facts are really one: a tuple can't change, so its fingerprint stays valid, so a dictionary will accept it as a key. Remember the chain and you never have to memorize the pieces separately.", "hook": "Fixed → fingerprint stays → dict key.", "calibration": "You felt unsure but got it fully right — trust this one more than you did."}}

Respond with ONLY a JSON object in this exact format. No markdown fences, no preamble:
{{"quality": <int 0-5>, "right": "<string>", "gap": "<string>", "why": "<string>", "hook": "<string>", "calibration": "<string>"}}
"""

    result = call_for_json(prompt, fast=True, max_tokens=650, purpose="grading")   # teaching "why" needs room
    result["correct_answer"] = correct_answer
    # composite text fallback for anything that renders feedback as one block
    parts = [p for p in [result.get("right"), result.get("gap"), result.get("why")] if p]
    result["feedback"] = " ".join(parts)
    return result


if __name__ == "__main__":
    question = "What is the difference between a list and a tuple in Python?"
    correct_answer = "Lists are mutable, tuples are immutable. Lists use [], tuples use (). Tuples can be dict keys, lists cannot."

    tests = [
        ("Lists can be changed, tuples can't.", "sure"),
        ("banana", None),
        ("Lists are mutable, tuples are immutable, and tuples can be dict keys.", "unsure"),
    ]
    for attempt, conf in tests:
        result = grade_answer(question, correct_answer, attempt, confidence=conf)
        print(f"--- {attempt!r} (confidence: {conf})")
        for key in ("quality", "right", "gap", "why", "hook", "calibration"):
            print(f"  {key}: {result.get(key)}")
        print()
