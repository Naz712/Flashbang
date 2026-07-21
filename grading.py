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

Then produce structured feedback fields:
- "right": what the attempt got correct, stated specifically ("" if nothing was right). Never generic praise — name the correct elements.
- "gap": exactly what was missing or wrong ("" if fully correct). Name the missing terms or the misconception, don't just say "some details".
- "why": ONE sentence of explanation that deepens understanding of the underlying idea — the mechanism or reason, not a restatement of the answer.
- "hook": a short memory cue for the next recall — a vivid association, contrast, or rule of thumb (max ~12 words).
- "calibration": ONLY if a stated confidence was given, one short note comparing confidence to performance. For a confident answer graded 0-2, flag it: confidently-held errors are the most correctable, but they come back without extra attention. For unsure-but-correct, note the recall was better than they felt. "" if no confidence stated.

Examples:

Question: "What is the difference between a list and a tuple in Python?"
Stored answer: "Lists are mutable, tuples are immutable. Lists use [], tuples use (). Tuples can be dict keys, lists cannot."

Attempt: "banana"
{{"quality": 0, "right": "", "gap": "No relevant content — the answer concerns mutability, syntax, and dict-key usability.", "why": "Immutability is the core property: it fixes a tuple's contents at creation, which is what makes it hashable.", "hook": "Tuple = sealed box; list = open box.", "calibration": ""}}

Attempt: "Lists can be changed, tuples can't." (confidence: sure)
{{"quality": 3, "right": "The core difference — lists are mutable, tuples immutable.", "gap": "Missing the syntax ([] vs ()) and that only tuples can be dictionary keys.", "why": "Because tuples can't change, their hash stays stable, so Python allows them as dict keys.", "hook": "Immutable → hashable → dict key.", "calibration": "Sure and mostly right — well calibrated; push for the last details."}}

Attempt: "Lists are changeable with square brackets; tuples are fixed, use parentheses, and can be dict keys." (confidence: unsure)
{{"quality": 5, "right": "Everything — mutability, syntax, and dict-key usability.", "gap": "", "why": "Immutability is what makes tuples hashable, which is why dicts accept them as keys.", "hook": "Immutable → hashable → dict key.", "calibration": "Unsure but fully correct — trust this memory more; it's stronger than it feels."}}

Respond with ONLY a JSON object in this exact format. No markdown fences, no preamble:
{{"quality": <int 0-5>, "right": "<string>", "gap": "<string>", "why": "<string>", "hook": "<string>", "calibration": "<string>"}}
"""

    result = call_for_json(prompt, fast=True, max_tokens=400)
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
