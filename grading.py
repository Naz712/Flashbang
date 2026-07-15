from dotenv import load_dotenv
import anthropic
import json

load_dotenv()
client = anthropic.Anthropic()

def grade_answer(question, correct_answer, user_answer):
    prompt = f"""You are a teacher grading my answer to the question stated on flashcards.

The question is: "{question}"
The correct answer for the question is: "{correct_answer}"
My answer is: "{user_answer}"

Grade my answer on a scale of 0 to 5:
0 = completely wrong, or unable to answer at all
1 = wrong, but I understood the question and made a relevant attempt
2 = wrong, with a misconception that's relevant to the topic
3 = correct main idea, but vague or missing key terminology
4 = correct with most details, missing some minor specifics
5 = fully correct, well-phrased, all key terms and details present

After the grade, write feedback:
- Grade 0: refresher on the concept, then the answer
- Grade 1-2: explain what I got wrong and the correct understanding, then the answer
- Grade 3-4: explain what key words or details I missed, then the answer
- Grade 5: brief acknowledgment, then restate the answer, stressing key details

Example:
Question: "What is the difference between a list and a tuple in Python?"
Correct answer: "Lists are mutable, tuples are immutable. Lists use [], tuples use (). Tuples can be dict keys, lists cannot."
User's answer: "Lists can be changed, tuples can't."
Output:
{{"quality": 3, "feedback": "You correctly identified the main difference (mutability), but missed the syntax differences ([] vs ()) and the practical implication that tuples can be used as dictionary keys."}}

"Feedback must be 1 to 2 sentences. Be direct and concise. No preamble like 'Your answer was...' — just state what's missing.
Respond with ONLY a JSON object in this exact format. No markdown code fences, no preamble:
{{"quality": <integer from 0 to 5>, "feedback": "<your feedback as a single string>"}}
"""

    response = client.messages.create(
        model="claude-haiku-4-5",   # fast model — grading a short answer doesn't need Sonnet
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_text = response.content[0].text
    return json.loads(raw_text)


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