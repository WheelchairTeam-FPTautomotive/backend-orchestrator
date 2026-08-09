# Ephemeral short-term memory (STM)

Privacy-first dialogue continuity for the Wheelchair Traceable Voice Copilot.

## What it is

- Gateway in-process store keyed by `session_id`
- Idle TTL presets: **0 / 3 / 5 / 10** minutes (default **5**)
- Max **6** turns; wiped on idle, `X-Session-Reset: 1`, or New chat
- Applies to **RAG + FREE_TALK** only — never CAR_CONTROL / REFUSED

## What it is not

- Not long-term chat memory
- Not vectorized chat history in Chroma
- Not disk-persisted driver speech

## Anaphora

Prior turns are sent as `conversation_context`. The Core **query planner** resolves pronouns into a standalone `search_query` for BM25/dense. The UI still shows the raw utterance; the LLM answer path also receives context for natural phrasing.

## Ops

Pin gateway Uvicorn to **1 worker** (`Dockerfile` CMD) so the in-process dict stays coherent.
