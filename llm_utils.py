"""Shared Anthropic client and robust JSON handling for all LLM calls.
Every module that calls Claude imports `client` and the JSON helpers from here
instead of creating its own client and doing raw json.loads on model output."""

import json
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()


def parse_json_response(raw_text):
    """Parse a model response that should be JSON, tolerating code fences and
    stray prose around the object/array. Raises json.JSONDecodeError if no
    valid JSON can be found."""
    text = raw_text.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences of any flavour
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # fall back to the outermost {...} or [...] span
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start, end = text.find(open_ch), text.rfind(close_ch)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue
        raise


def call_for_json(prompt, model="claude-sonnet-4-5", max_tokens=4000):
    """One-shot Claude call that must return JSON. Retries ONCE on a parse
    failure by showing the model its own bad output. Raises RuntimeError if the
    response was truncated (stop_reason max_tokens) — truncated JSON must never
    be silently parsed — or if the retry also fails to parse."""
    messages = [{"role": "user", "content": prompt}]
    for attempt in range(2):
        response = client.messages.create(
            model=model, max_tokens=max_tokens, messages=messages,
        )
        raw_text = response.content[0].text
        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                f"LLM response truncated at {max_tokens} tokens; raise max_tokens "
                f"or shrink the input. First 200 chars: {raw_text[:200]}"
            )
        try:
            return parse_json_response(raw_text)
        except json.JSONDecodeError as e:
            if attempt == 1:
                raise RuntimeError(
                    f"LLM returned unparseable JSON twice. Error: {e}. "
                    f"Raw output: {raw_text[:500]}"
                )
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({
                "role": "user",
                "content": f"Your output was not valid JSON ({e}). "
                           "Respond again with ONLY the valid JSON, nothing else.",
            })
