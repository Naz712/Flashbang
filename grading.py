from llm_utils import client, parse_json_response


def grade_answer(question, correct_answer, user_answer):
    prompt = f"""You are grading a student's flashcard recall attempt.

Question: "{question}"
Stored correct answer: "{correct_answer}"
Student's attempt: "{user_answer}"

Grade the attempt on a scale of 0 to 5:
0 = completely wrong, or unable to answer at all
1 = wrong, but the student understood the question and made a relevant attempt
2 = wrong, with a misconception that's relevant to the topic
3 = correct main idea, but vague or missing key terminology
4 = correct with most details, missing some minor specifics
5 = fully correct, all key ideas and details present

Grade meaning, not wording: do NOT penalize paraphrasing or a different phrasing
from the stored answer. If the student's attempt conveys the same facts in their
own words, it is correct.

After the grade, write feedback:
- Grade 0: refresher on the concept, then the answer
- Grade 1-2: explain what the student got wrong and the correct understanding, then the answer
- Grade 3-4: explain what key words or details were missed, then the answer
- Grade 5: brief acknowledgment, then restate the answer, stressing key details

Examples (note the full range — do not cluster grades toward the middle):

Question: "What is the difference between a list and a tuple in Python?"
Stored answer: "Lists are mutable, tuples are immutable. Lists use [], tuples use (). Tuples can be dict keys, lists cannot."
Attempt: "banana"
Output:
{{"quality": 0, "feedback": "Lists and tuples are both ordered collections; the key difference is lists can be modified after creation (mutable) while tuples cannot (immutable). Lists use [], tuples use (), and only tuples can serve as dictionary keys."}}

Attempt: "Lists can be changed, tuples can't."
Output:
{{"quality": 3, "feedback": "You correctly identified the main difference (mutability), but missed the syntax differences ([] vs ()) and the practical implication that tuples can be used as dictionary keys."}}

Attempt: "Lists are changeable and written with square brackets; tuples can't be modified, use parentheses, and unlike lists they can be dictionary keys."
Output:
{{"quality": 5, "feedback": "Fully correct. Lists are mutable ([]), tuples are immutable (()), and immutability is what lets tuples act as dictionary keys."}}

Feedback must be 1 to 2 sentences. Be direct and concise. No preamble like 'Your answer was...' — just state what's missing.
Respond with ONLY a JSON object in this exact format. No markdown code fences, no preamble:
{{"quality": <integer from 0 to 5>, "feedback": "<your feedback as a single string>"}}
"""

    response = client.messages.create(
        model="claude-haiku-4-5",   # fast model — grading a short answer doesn't need Sonnet
        max_tokens=300,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": '{"quality":'},  # prefill locks the JSON shape
        ]
    )

    raw_text = '{"quality":' + response.content[0].text
    return parse_json_response(raw_text)


if __name__ == "__main__":
    question = "What is the difference between a list and a tuple in Python?"
    correct_answer = "Lists are mutable, tuples are immutable. Lists use [], tuples use (). Tuples can be dict keys, lists cannot."

    test_answers = [
        "Lists can be changed, tuples can't.",
        "Lists use [] and tuples use ().",
        "They're both ordered collections.",
        "Lists are mutable, tuples are immutable. Lists use [], tuples use (). Tuples can be dict keys.",
        "banana",
    ]

    for i, user_answer in enumerate(test_answers, 1):
        print(f"--- Test {i}: {user_answer!r} ---")
        result = grade_answer(question, correct_answer, user_answer)
        print(f"  Grade: {result['quality']}/5")
        print(f"  Feedback: {result['feedback']}")
        print()
