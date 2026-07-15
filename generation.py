from dotenv import load_dotenv
import anthropic
import json

load_dotenv()
client = anthropic.Anthropic()

def extract_concepts(notes):
    prompt = f"""You are an expert at reading study notes and identifying the key concepts within them.

INPUTS:
The notes to analyze:
{notes}

TASK:
Read through the notes and identify the key concepts. For each concept, extract the exact verbatim text from the notes that pertains to it.

Key concepts are important ideas or principles essential to understanding the material or solving problems related to the topic. They often include definitions, formulas, processes, or relationships between ideas.

Content should be the exact verbatim text from the notes that pertains to this concept — including any examples, formulas, or code blocks. Do not paraphrase, summarize, or rewrite.

For any text that pertains to more than one concept, include it under both concepts.

For any text that does not pertain to any concept, include it verbatim in the "uncategorized" field so nothing is silently dropped.

Focus on content that actually helps me understand the concept covered by the notes. Do not include fun facts, historical context, or other non-essential information that doesn't directly contribute to understanding the core concepts.

EXAMPLE OUTPUT:
{{
    "subject": "Java",
    "topic": "Inheritance",
    "concepts": [
        {{
            "name": "extends",
            "content": "The keyword extends declares that a class inherits from another class. The class that inherits is called the child class, and the class being inherited from is called the parent class. The child class gains the properties and methods of the parent class."
        }},
        {{
            "name": "method overriding",
            "content": "Method overriding occurs when a child class provides a specific implementation of a method that is already defined in its parent class. The child class's version of the method replaces the parent's version when called on a child class instance."
        }},
        {{
            "name": "super",
            "content": "The super() function can be used to call methods from the parent class within the child class. This is useful when the child class wants to extend the parent's behavior rather than fully replace it."
        }}
    ],
    "uncategorized": ""
}}

OUTPUT FORMAT:
MAKE SURE YOU respond with ONLY a JSON object in this exact format. No markdown code fences, no preamble. Follow this strictly:
{{
    "subject": "<string, e.g. 'Java'>",
    "topic": "<string, e.g. 'Inheritance'>",
    "concepts": [
        {{
            "name": "<string, e.g. 'extends'>",
            "content": "<string, verbatim text from the notes pertaining to this concept>"
        }}
    ],
    "uncategorized": "<string, verbatim leftover text from the notes that didn't fit any concept, or empty string if everything was categorized>"
}}
"""


    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_text = response.content[0].text
    raw_text = raw_text.removeprefix("```json\n")
    raw_text = raw_text.removesuffix("\n```")
    return json.loads(raw_text) 

def generate_cards(subject, topic, concepts, count):
     
    count = min(count, 80)
    concepts_text = "\n\n".join(
        f"Concept: {c['name']}\nContent: {c['content']}"
        for c in concepts
    )

    prompt = f"""You are a educator creating flashcards for students based on the key concepts and the text tied to those concepts.
        INPUTS:
        Subject: {subject}
        Topic: {topic}

        The concepts and their verbatim text:
        {concepts_text}

        TASK:
        For the given subject and topic, create up to {count} flashcards with questions and answers based on the concepts and their verbatim text.
        Generate up to {count} flashcards. Use fewer if the concept doesn't warrant {count} testable facts. Generate only as many cards as the content genuinely supports — never invent or pad.
        You may parphrase the text when creating the question and answer in order to make the explanation clearer and more concise but the content cannot be compromised and must capture the full meaning of the original text.
        For the flashcards, cover one card per fact. Do not combine multiple facts into one card. If a concept has multiple distinct facts, create multiple cards for that concept.
        Critical rule: one fact per card. If a sentence in the source notes uses 'and', 'or', or lists items, those items must become separate cards. For example: 'open addressing uses linear probing or quadratic probing' should produce THREE cards (one on open addressing, one on linear probing, one on quadratic probing), not one bundled card.
        Questions must be unambiguous and have a single correct answer that can be directly supported by the verbatim text. Do not create questions that are opinion-based, open-ended, or that require synthesis of multiple concepts.
        Do not create questions whose answers are lists or sets of items. If you want to test a list, make one card per item instead."
        When making coding related cards, use concepts over derivable facts. For example, if the concept is a code snippet, the card should ask about the purpose of the code or what it does, not just what the output is. The answer should explain the concept and how it works, not just give the output.
        Answers should be 1 to 3 sentences. Long enough to include reasoning, short enough to be reasonable to recall.
        Mix factual recall questions ('what...') with 'why' questions that probe understanding.


        EXAMPLE OUTPUT:
        [
            {{
                "subject": "Biology",
                "topic": "Photosynthesis",
                "question": "Where do the light-dependent reactions of photosynthesis take place?",
                "answer": "In the thylakoid membranes of the chloroplast."
            }},
            {{
                "subject": "Biology",
                "topic": "Photosynthesis",
                "question": "Why do most plants appear green?",
                "answer": "Chlorophyll absorbs light strongly in the blue and red regions of the visible spectrum and reflects green light, which is what reaches our eyes."
            }},
            {{
                "subject": "Biology",
                "topic": "Photosynthesis",
                "question": "What is the role of ATP and NADPH in photosynthesis?",
                "answer": "They are carrier molecules produced by the light-dependent reactions that store energy temporarily and supply it to the Calvin cycle, where it is used to fix carbon dioxide into glucose."
            }}
        ]

        OUTPUT FORMAT:
        MAKE SURE YOU respond with ONLY a JSON array in this exact format. No markdown code fences, no preamble. Follow this strictly:
        [
            {{
                "subject": <string, e.g. 'Biology'>,
                "topic": <string, e.g.'Photosynthesis'>,
                "question": <string, e.g.'Where do the light-dependent reactions of photosynthesis take place?'>,
                "answer": <string, e.g.'In the thylakoid membranes of the chloroplast.'>
            }}
        ]
        """
    
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    raw_text = response.content[0].text
    raw_text = raw_text.removeprefix("```json\n")
    raw_text = raw_text.removesuffix("\n```")
    return json.loads(raw_text)

if __name__ == "__main__":
    test_notes = """A hash table is a data structure that stores key-value pairs and allows fast lookup, insertion, and deletion in average O(1) time. It works by passing each key through a hash function, which converts the key into an integer index that points to a slot in an underlying array.

A hash function is the core mechanism that maps keys to array indices. A good hash function distributes keys uniformly across the available slots so tha lookups stay fast. A bad hash function clusters many keys into the same slot and degrades performance toward O(n).

When two different keys hash to the same index, this is called a collision. Collisions are inevitable because the set of possible keys is usually much larger than the size of the array. Hash tables must have a strategy for handling collisions in order to remain correct.

One common strategy for handling collisions is chaining, where each slot in the array holds a linked list of all key-value pairs whose keys hash to that index. Lookups in a chained slot are linear in the length of the chain, so performance depends on keeping chains short.

Another strategy is open addressing, where collisions are resolved by probing nearby slots until an empty one is found. Variants include linear probing, where the algorithm checks the next slot in sequence, and quadratic probing, which checks slots at increasing intervals.

The load factor of a hash table is the ratio of stored entries to total slots. As the load factor grows, collisions become more frequent and performance degrades. Most hash table implementations resize the underlying array once the load factor crosses a threshold, typically around 0.7."""
    
    # Step 1: extract concepts (already works)
    extracted = extract_concepts(test_notes)
    print("--- extracted ---")
    print(extracted)
    print()
    
    # Step 2: generate cards from those concepts
    cards = generate_cards(
        subject=extracted["subject"],
        topic=extracted["topic"],
        concepts=extracted["concepts"],
        count=8
    )
    print("--- cards ---")
    for card in cards:
        print(card)
        print()