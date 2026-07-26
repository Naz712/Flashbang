"""LLM provider layer. Auto-detects Anthropic or OpenAI from whichever API key
is present in .env (Anthropic preferred if both). Everything above this module
is provider-agnostic: agent_core's tool loop branches on PROVIDER, and all
one-shot calls go through complete_text() / call_for_json().

Model tiers: 'main' for reasoning-heavy work (agent turns, segmentation,
card generation), 'fast' for cheap calls (grading, routing)."""

import os
import json
from dotenv import load_dotenv

load_dotenv()

if os.getenv("ANTHROPIC_API_KEY"):
    PROVIDER = "anthropic"
    MAIN_MODEL = "claude-sonnet-4-5"
    FAST_MODEL = "claude-haiku-4-5"
elif os.getenv("OPENAI_API_KEY"):
    PROVIDER = "openai"
    MAIN_MODEL = os.getenv("OPENAI_MAIN_MODEL", "gpt-4o")
    FAST_MODEL = os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini")
else:
    PROVIDER = None  # importable without keys (dashboard-only); calls will raise
    MAIN_MODEL = FAST_MODEL = None

_anthropic_client = None
_openai_client = None
_chat_models = {}

# Custom OpenAI-compatible endpoint (Agnes AI / GMI Cloud sponsor credits):
# point OPENAI_BASE_URL + OPENAI_MAIN_MODEL/OPENAI_FAST_MODEL at the provider.
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
# Helicone observability (free tier): set HELICONE_API_KEY and requests proxy
# through Helicone for real per-request cost/latency dashboards. An explicit
# OPENAI_BASE_URL takes precedence.
HELICONE_API_KEY = os.getenv("HELICONE_API_KEY")


def _openai_endpoint():
    """(base_url, default_headers) for the active OpenAI-compatible endpoint."""
    if OPENAI_BASE_URL:
        return OPENAI_BASE_URL, {}
    if HELICONE_API_KEY:
        return "https://oai.helicone.ai/v1", {"Helicone-Auth": f"Bearer {HELICONE_API_KEY}"}
    return None, {}


def anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


def openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        base_url, headers = _openai_endpoint()
        _openai_client = OpenAI(base_url=base_url, default_headers=headers or None)
    return _openai_client


def chat_model(fast=False):
    """LangChain chat model for the active provider (frameworks fork) — used by
    the LangGraph agent loop. One code path replaces the two hand-rolled
    provider dialects; base_url/Helicone plumbing rides along for free."""
    _require_provider()
    key = ("fast" if fast else "main")
    if key not in _chat_models:
        model_name = FAST_MODEL if fast else MAIN_MODEL
        if PROVIDER == "anthropic":
            from langchain_anthropic import ChatAnthropic
            _chat_models[key] = ChatAnthropic(model=model_name, max_tokens=4096)
        else:
            from langchain_openai import ChatOpenAI
            base_url, headers = _openai_endpoint()
            _chat_models[key] = ChatOpenAI(model=model_name, max_completion_tokens=4096,
                                           base_url=base_url,
                                           default_headers=headers or None)
    return _chat_models[key]


def _require_provider():
    if PROVIDER is None:
        raise RuntimeError(
            "No LLM API key found. Create a .env file in the project folder with "
            "OPENAI_API_KEY=... (or ANTHROPIC_API_KEY=...) and restart the app.")


def complete_text(prompt, fast=False, max_tokens=1000):
    """One-shot text completion on either provider."""
    _require_provider()
    model = FAST_MODEL if fast else MAIN_MODEL
    if PROVIDER == "anthropic":
        response = anthropic_client().messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}])
        return response.content[0].text, response.stop_reason == "max_tokens"
    else:
        response = openai_client().chat.completions.create(
            model=model, max_completion_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}])
        choice = response.choices[0]
        return choice.message.content or "", choice.finish_reason == "length"


def parse_json_response(raw_text):
    """Parse a model response that should be JSON, tolerating code fences and
    stray prose around the object/array. Raises json.JSONDecodeError if no
    valid JSON can be found."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start, end = text.find(open_ch), text.rfind(close_ch)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue
        raise


def call_for_json(prompt, fast=False, max_tokens=4000):
    """One-shot call that must return JSON. Retries ONCE on a parse failure by
    showing the model its own bad output. Raises RuntimeError on truncation
    (truncated JSON must never be silently parsed) or a second parse failure."""
    current_prompt = prompt
    for attempt in range(2):
        raw_text, truncated = complete_text(current_prompt, fast=fast, max_tokens=max_tokens)
        if truncated:
            raise RuntimeError(
                f"LLM response truncated at {max_tokens} tokens; raise max_tokens "
                f"or shrink the input. First 200 chars: {raw_text[:200]}")
        try:
            return parse_json_response(raw_text)
        except json.JSONDecodeError as e:
            if attempt == 1:
                raise RuntimeError(
                    f"LLM returned unparseable JSON twice. Error: {e}. "
                    f"Raw output: {raw_text[:500]}")
            current_prompt = (prompt +
                              f"\n\nYour previous output was not valid JSON ({e}). "
                              "Respond with ONLY the valid JSON, nothing else.")
