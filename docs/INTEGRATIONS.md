# Integrations — sponsor credits & observability

All LLM traffic flows through `llm_utils.py`, so switching providers or
adding observability is a `.env` change. Restart the server after editing.

## OpenAI (default)

```
OPENAI_API_KEY=sk-...
```

## Agnes AI credits (OpenAI-compatible endpoint)

Their public docs 404 — grab the base URL and model ids from the Agnes
dashboard, then:

```
OPENAI_API_KEY=<agnes key>
OPENAI_BASE_URL=<agnes endpoint, e.g. https://api.agnes-ai.com/v1>
OPENAI_MAIN_MODEL=<agnes model id>
OPENAI_FAST_MODEL=<agnes cheap model id>
```

## GMI Cloud credits (OpenAI-compatible inference, open models)

```
OPENAI_API_KEY=<gmi key>
OPENAI_BASE_URL=https://api.gmi-serving.com/v1   # verify in the GMI console
OPENAI_MAIN_MODEL=<model id from the GMI catalog>
OPENAI_FAST_MODEL=<smaller model id>
```

**Caveat:** open models vary in tool-calling quality. gpt-4o stays the safe
choice for the agent loop; aggregator credits are best burned on single-shot
pipelines (topic segmentation, card generation, grading). Embeddings are
LOCAL (Chroma ONNX MiniLM) on this branch — no embedding key needed at all.

## Helicone observability (free tier)

Real per-request cost/latency dashboards instead of estimates:

```
HELICONE_API_KEY=sk-helicone-...
```

Requests proxy through `oai.helicone.ai`. An explicit `OPENAI_BASE_URL`
takes precedence — Agnes/GMI endpoints and Helicone don't stack.
