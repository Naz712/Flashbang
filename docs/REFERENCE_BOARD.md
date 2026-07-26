# Flashbang Reference Board — hand-rolled ↔ framework

Permanent map of every subsystem: what was hand-built, which library/service
replaces it, the code on both sides, and why. The hand-rolled originals live
on `master` (and in this branch's git history); this branch (`frameworks`)
runs the right-hand column. Served at `/reference` in the app.

---

## 1. Agent tool loop — `run_turn` → **LangGraph** (ADOPTED here)

**Hand-rolled** (`agent_core.py` on master): a while-loop per provider dialect —
Anthropic `tool_use` blocks / OpenAI `tool_calls` — dispatching through the
handler registry until the model stops calling tools.

```python
while True:
    response = client.messages.create(model=..., system=prompt,
                                      tools=tools, messages=messages)
    if response.stop_reason == "tool_use":
        for block in response.content:
            result = handle_tool(block.name, block.input)
            tool_results.append({"type": "tool_result", ...})
        messages.append({"role": "user", "content": tool_results})
        continue
    return final_text
```

**Framework** (this branch): one prebuilt ReAct agent per specialist.

```python
from langgraph.prebuilt import create_react_agent
graph = create_react_agent(chat_model(), lc_tools, prompt=agent.build_system_prompt())
result = graph.invoke({"messages": messages}, config={"recursion_limit": 60})
```

**Why / trade-off:** ~100 lines of provider-dialect code deleted; streaming,
retries, and parallel tool calls come free. Trade-off: less control over the
loop (the thread-local callback bug below only existed *because* the
framework runs tools on its own threads), and debugging goes through
framework abstractions. Hard-won lesson: guardrails must live in the tool
wrapper, not the loop, to survive a framework swap.

## 2. Provider switching — `llm_utils` branches → **LangChain model classes** (ADOPTED)

Hand-rolled: `if PROVIDER == "anthropic": ... else: ...` at every call site
that mattered. Framework: `ChatAnthropic` / `ChatOpenAI` behind one
`chat_model()` factory; `base_url` support (Agnes AI / GMI Cloud sponsor
credits) and Helicone headers ride along. **Alternative not adopted:**
LiteLLM (100+ providers, one `completion()` call) — the right choice if
single-shot pipelines (grading/segmentation) should also switch providers
freely.

## 3. Spaced repetition — `sm2.py` → **py-fsrs** (EVALUATED → REVERTED by choice)

**Hand-rolled:** textbook SM-2, 17 lines — quality < 3 resets to 1 day, else
interval 1 → 6 → interval × ease.

```python
ease += (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
interval = 1 if q < 3 else round(interval * ease)
```

**Framework:** FSRS (modern Anki's scheduler) via `fsrs_adapter.py` — each
card carries learned *stability* and *difficulty*; `desired_retention=0.75`
keeps the app's "due ⇒ 75%" story; mastery decay reads FSRS's power-law
curve with the old exponential as legacy fallback.

```python
scheduler = Scheduler(desired_retention=0.75, learning_steps=(), enable_fuzzing=False)
card, _ = scheduler.review_card(card, QUALITY_TO_RATING[quality])
```

**Observed difference (real card, same answer):** first Good review → SM-2
gave 1 day; FSRS gave **13 days**. FSRS also (correctly) gives ~zero
stability gain for an immediate same-day repeat — massed repetition adds no
durable memory.

**Eval outcome → reverted to SM-2.** At `desired_retention=0.75`, intervals
stretched to months (13 → 156 → 1294 days on steady Good) — mathematically
consistent ("review only when recall falls to 75%") but too sparse for
exam-driven study. The decision: SM-2's tighter rhythm wins for this use
case. `fsrs_adapter.py` stays; re-adoption is one import plus
`Scheduler(desired_retention=0.9, maximum_interval=90)` for Anki-like
intervals (1d, 4d, 10d, 25d).

## 4. Semantic search — `embeddings.py` + `search.py` → **Chroma** (ADOPTED)

**Hand-rolled:** OpenAI `text-embedding-3-small` per concept, vectors as JSON
strings in a SQLite column, numpy cosine over every row.

```python
score = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
```

**Framework:** `chromadb.PersistentClient` collection with the default LOCAL
ONNX MiniLM embedding — zero API cost, offline, metadata filters for
course/pdf/topic scoping, deletes mirrored to the SQL cascades.

```python
collection.query(query_texts=[text], n_results=k, where={"course_id": {"$eq": cid}})
```

**Trade-off:** local MiniLM embeddings are cheaper but weaker than OpenAI's;
similarity scores rescale (the 0.3 relevance threshold means something
different). Vector data now lives in `chroma/`, rebuildable via
`backfill_embedding.py`.

## 5. Router + session pinning — KEPT hand-rolled (LangGraph state graphs exist)

The 3-layer router (pin fast-path → keywords → 10-token classifier) and
tool-call-derived pinning could be a LangGraph `StateGraph` with conditional
edges. Kept ours: it's ~80 lines, fully understood, the pin fast-path costs
zero API calls, and it earned its design through two real routing bugs.

## 6. Structured LLM output — `call_for_json` → Instructor (AVAILABLE, not adopted)

Our retry-once JSON parser works; Instructor would add pydantic-validated
outputs with automatic re-asking. Worth adopting if output schemas grow.

## 7. PDF parsing — `pdf_ingest.py` → LlamaParse / Unstructured (AVAILABLE, not adopted)

The pypdf-first + vision-fallback pipeline extracted a 242-page deck with
zero vision calls for ~$0. A parsing SaaS would simplify code but add cost,
a dependency, and uploads of course material to a third party.

## 8. Observability — none → **Helicone** (WIRED, env-gated)

Set `HELICONE_API_KEY` in `.env` → OpenAI traffic proxies through Helicone
for real per-request cost/latency dashboards. Explicit `OPENAI_BASE_URL`
takes precedence (can't stack with Agnes/GMI endpoints).

---

*Bug ledger for this branch:* thread-local turn callbacks died on LangGraph's
tool-executor threads (pinning + grade cards silently dead) → module-level
turn context. Test expectation bug: asserting stability growth on an
immediate re-review — FSRS correctly gives none; the test now spaces the
reviews.
