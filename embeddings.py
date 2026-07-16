from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
_client = None


def _get_client():
    # lazy: constructing OpenAI() without OPENAI_API_KEY raises, and this module
    # is imported by database.py — the app must be importable without keys
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def embed_text(text):
    response = _get_client().embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding
